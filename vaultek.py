"""
VAULTEK - encrypted credential vault, blue glossy glass edition.

pip install pillow pycryptodome rapidfuzz requests

The master password is typed at every launch and is NEVER stored in this file.
It is stretched with scrypt into the AES-256-GCM key, so the .exe alone (or the
repo alone) can't decrypt anything.
"""
import base64, copy, ctypes, datetime, json, math, os, queue, socket, sys, threading, time
import tkinter as tk
from tkinter import messagebox

import requests
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import scrypt
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageOps, ImageTk
from rapidfuzz import fuzz, process

# =====================================================================
# CONFIG
# =====================================================================


PAT_PLAIN = ""   # this is where you put your repo api token and make sure it has """"" read write permissions for 'content' """"" (VERY IMPORTANT)


PAT_MASKED = []   # for added security you could also put a masked token! but it dosent matter since we're using nuitka to pack it (Serious security)

GITHUB_REPO = "gutsfromberserk1re(ur-username-here)/repo-name-here" #put YOURRRRR user and repo. dont have too many folders to overcomplicated things. 

VAULT_FILE = "vault.json" #autocreates on first run) #also make sure the repo is private yeah?

BG_PATH = "background1.jpg" #background image i wanted ignore if u dont want one

ICON_PATH = "vaultek.ico" #icon i set u can have ur own icon
# =====================================================================

W, H = 980, 700
PC = socket.gethostname()
PAD = 12
CW, CH, GAP = 850, 118, 12
PH = "Search"
try:
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    LANCZOS = Image.LANCZOS


def unmask(b, k=0x7F):
    return "".join(chr(x ^ k) for x in b)


TOKEN = PAT_PLAIN or unmask(PAT_MASKED)


def antidebug():
    if sys.platform == "win32" and ctypes.windll.kernel32.IsDebuggerPresent():
        sys.exit(1)


b64e = lambda b: base64.b64encode(b).decode()
b64d = lambda s: base64.b64decode(s)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ago(t):
    try:
        d = datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
        s = (datetime.datetime.now(datetime.timezone.utc) - d).total_seconds()
    except Exception:
        return "?"
    if s < 90: return "just now"
    if s < 3600: return f"{int(s // 60)}m ago"
    if s < 172800: return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"


def trunc(s, n=64):
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


# ---------------------------------------------------------------------
# DATA MODEL + MERGE (keeps two PCs from overwriting each other)
# ---------------------------------------------------------------------
def norm(d):
    if isinstance(d, list):
        d = {"entries": d}
    d = d or {}
    return {"entries": d.get("entries", []), "deleted": d.get("deleted", []), "devices": d.get("devices", {})}


def merge(a, b):
    dele = set(a["deleted"]) | set(b["deleted"])
    ents = {}
    for e in a["entries"] + b["entries"]:
        if e.get("id") in dele:
            continue
        o = ents.get(e.get("id"))
        if not o or e.get("updatedAt", "") >= o.get("updatedAt", ""):
            ents[e.get("id")] = e
    dev = dict(a["devices"])
    for k, v in b["devices"].items():
        if v > dev.get(k, ""):
            dev[k] = v
    return {"entries": sorted(ents.values(), key=lambda e: str(e.get("id"))),
            "deleted": sorted(dele), "devices": dev}


# ---------------------------------------------------------------------
# CRYPTO + GITHUB
# ---------------------------------------------------------------------
class Vault:
    def __init__(self):
        self.key = self.salt = self.sha = None

    def url(self):
        return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{VAULT_FILE}"

    def hdr(self):
        return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

    def derive(self, pw, salt):
        return scrypt(pw.encode(), salt, 32, N=2 ** 15, r=8, p=1)

    def encrypt(self, data):
        c = AES.new(self.key, AES.MODE_GCM)
        ct, tag = c.encrypt_and_digest(json.dumps(data).encode())
        return {"v": 2, "salt": b64e(self.salt), "nonce": b64e(c.nonce), "tag": b64e(tag), "data": b64e(ct)}

    def decrypt(self, p, key=None):
        try:
            c = AES.new(key or self.key, AES.MODE_GCM, nonce=b64d(p["nonce"]))
            return json.loads(c.decrypt_and_verify(b64d(p["data"]), b64d(p["tag"])))
        except Exception:
            return None

    def fetch(self):
        try:
            r = requests.get(self.url(), headers=self.hdr(), timeout=15)
        except requests.RequestException:
            return ("error", "Can't reach GitHub (offline?)")
        if r.status_code == 404:
            self.sha = None
            return ("missing", None)
        if r.status_code in (401, 403):
            return ("error", "GitHub rejected the token")
        if r.status_code != 200:
            return ("error", f"GitHub error {r.status_code}")
        try:
            j = r.json()
            self.sha = j["sha"]
            return ("ok", json.loads(b64d(j["content"])))
        except Exception:
            return ("error", "Vault file is corrupted")

    def open(self, pw):
        st, p = self.fetch()
        if st == "error": return (st, p)
        if st == "missing": return ("new",)
        try:
            salt = b64d(p["salt"])
        except Exception:
            return ("error", "Unrecognised vault format")
        key = self.derive(pw, salt)
        d = self.decrypt(p, key)
        if d is None: return ("wrong",)
        self.key, self.salt = key, salt
        return ("ok", norm(d))

    def create(self, pw):
        self.salt = os.urandom(16)
        self.key = self.derive(pw, self.salt)
        return ("ok", norm({}))

    def pull(self):
        st, p = self.fetch()
        if st != "ok": return ("error", "pull failed")
        d = self.decrypt(p)
        return ("ok", norm(d)) if d is not None else ("error", "unreadable")

    def push(self, data):
        body = {"message": "vault update", "content": b64e(json.dumps(self.encrypt(data)).encode())}
        if self.sha:
            body["sha"] = self.sha
        try:
            r = requests.put(self.url(), headers=self.hdr(), json=body, timeout=20)
        except requests.RequestException:
            return ("error", "Can't reach GitHub (offline?)")
        if r.status_code in (200, 201):
            self.sha = r.json()["content"]["sha"]
            return ("ok",)
        if r.status_code in (409, 422):
            return ("conflict",)
        return ("error", f"GitHub error {r.status_code}")

    def push_merge(self, data):
        for _ in range(4):
            r = self.push(data)
            if r[0] == "ok": return ("ok", data)
            if r[0] != "conflict": return r
            st, p = self.fetch()
            remote = self.decrypt(p) if st == "ok" else None
            if remote is None: return ("error", "couldn't merge remote changes")
            data = merge(data, norm(remote))
        return ("error", "too many conflicts")


# ---------------------------------------------------------------------
# GLASS RENDERING (Pillow)
# ---------------------------------------------------------------------
def font(size, bold=False):
    for n in ("segoeuib.ttf" if bold else "segoeui.ttf", "arial.ttf"):
        try: return ImageFont.truetype(n, size)
        except OSError: pass
    return ImageFont.load_default()


def rmask(w, h, r):
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1], r * 4, fill=255)
    return m.resize((w, h), LANCZOS)


def rim(w, h, r, color, width, alpha):
    l = Image.new("RGBA", (w * 4, h * 4), (0, 0, 0, 0))
    ImageDraw.Draw(l).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1], r * 4, outline=color + (alpha,), width=width * 4)
    return l.resize((w, h), LANCZOS)


def gloss_layer(w, h, s):
    ga = ImageOps.invert(Image.linear_gradient("L").resize((w, max(1, h // 2)))).point(lambda v: v * s // 255)
    t = Image.new("RGBA", (w, max(1, h // 2)), (255, 255, 255, 0))
    t.putalpha(ga)
    full = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    full.paste(t, (0, 0))
    return full


def make_background(w, h, path=BG_PATH):
    if path and os.path.exists(path):
        return ImageOps.fit(Image.open(path).convert("RGBA"), (w, h), LANCZOS)
    g = ImageOps.colorize(Image.linear_gradient("L").resize((w, h)), (38, 135, 215), (3, 14, 48)).convert("RGBA")
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse([w * .2, -h * .25, w * .8, h * .2], fill=(120, 215, 255, 200))
    d.ellipse([-w * .15, h * .25, w * .12, h * .6], fill=(80, 190, 255, 170))
    d.ellipse([w * .88, h * .2, w * 1.15, h * .55], fill=(80, 190, 255, 150))
    d.ellipse([w * .25, h * .9, w * .75, h * 1.2], fill=(60, 150, 240, 150))
    return Image.alpha_composite(g, glow.filter(ImageFilter.GaussianBlur(70)))


def glass(bg, box, r=18, tint=(8, 44, 104), ta=110, blur=16, gloss=80, edge=(140, 225, 255), alpha=255):
    """Blurred, tinted, glossy glass with a glowing rim. Returns an RGBA layer with PAD margin."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if bg is None:
        base = Image.new("RGBA", (w, h), tint + (ta,))
    else:
        base = Image.alpha_composite(bg.crop(box).filter(ImageFilter.GaussianBlur(blur)),
                                     Image.new("RGBA", (w, h), tint + (ta,)))
    if gloss:
        base = Image.alpha_composite(base, gloss_layer(w, h, gloss))
    base = Image.alpha_composite(base, rim(w, h, r, edge, 2, 230))
    layer = Image.new("RGBA", (w + 2 * PAD, h + 2 * PAD), (0, 0, 0, 0))
    halo = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    halo.paste(rim(w, h, r, edge, 4, 200), (PAD, PAD))
    layer = Image.alpha_composite(layer, halo.filter(ImageFilter.GaussianBlur(5)))
    mk = rmask(w, h, r).point(lambda v: v * alpha // 255)
    base.putalpha(mk if bg is not None else ImageChops.multiply(base.getchannel("A"), mk))
    tmp = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    tmp.paste(base, (PAD, PAD))
    return Image.alpha_composite(layer, tmp)


def compose(bg, panels):
    out = bg.copy()
    for box, kw in panels:
        out.alpha_composite(glass(out, box, **kw), (box[0] - PAD, box[1] - PAD))
    return out


def make_button(w, h, text="", hover=False):
    r = h // 2
    top, bot = ((150, 230, 255), (30, 130, 225)) if hover else ((110, 205, 255), (20, 100, 200))
    col = ImageOps.colorize(Image.linear_gradient("L").resize((w, h)), top, bot).convert("RGBA")
    col = Image.alpha_composite(col, gloss_layer(w, h, 120))
    col = Image.alpha_composite(col, rim(w, h, r, (255, 255, 255), 2, 230))
    d = ImageDraw.Draw(col)
    if text == "+":
        cx, cy, L = w // 2, h // 2, int(h * .22)
        d.line([cx - L, cy, cx + L, cy], fill="white", width=3)
        d.line([cx, cy - L, cx, cy + L], fill="white", width=3)
    elif text:
        try:
            d.text((w // 2, h // 2 + 1), text, font=font(15, True), fill=(255, 255, 255, 255), anchor="mm")
        except Exception:
            d.text((10, h // 3), text, fill="white")
    layer = Image.new("RGBA", (w + 2 * PAD, h + 2 * PAD), (0, 0, 0, 0))
    halo = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    halo.paste(rim(w, h, r, (130, 225, 255), 4, 255 if hover else 170), (PAD, PAD))
    layer = Image.alpha_composite(layer, halo.filter(ImageFilter.GaussianBlur(5)))
    layer.paste(col, (PAD, PAD), rmask(w, h, r))
    return ImageTk.PhotoImage(layer)


# ---------------------------------------------------------------------
# WATER + LIGHT ANIMATION
# ---------------------------------------------------------------------
BIL = getattr(Image, "Resampling", Image).BILINEAR
LW, LH = 360, 220          # size of the small login window
KEY = "#010203"            # colour Windows makes see-through around the login glass


class Shimmer:
    """Drifting caustic 'water light' plus a slow light sweep, drawn over a static glass base."""

    def __init__(self, base, strength=100, scale=3):
        self.base = base.convert("RGBA")
        self.w, self.h = self.base.size
        self.hw, self.hh = max(8, self.w // scale), max(8, self.h // scale)
        self.strength = strength
        self.t1 = self.tex(self.hw * 2, self.hh * 2, 5)
        self.t2 = self.tex(self.hw * 2, self.hh * 2, 8)
        gh = int(self.hh * 2.4)
        g = Image.new("L", (int(self.hw * .9), gh), 0)
        ImageDraw.Draw(g).ellipse([g.width * .3, gh * .08, g.width * .7, gh * .92], fill=110)
        self.glare = g.filter(ImageFilter.GaussianBlur(self.hw * .05)).rotate(-22, resample=BIL, expand=True)

    @staticmethod
    def tex(w, h, blur):
        n = ImageOps.autocontrast(Image.effect_noise((w, h), 70).filter(ImageFilter.GaussianBlur(blur)))
        return n.point(lambda v: max(0, 255 - abs(v - 128) * 22))

    def frame(self, t, base=None):
        hw, hh, s, c = self.hw, self.hh, math.sin, math.cos
        o1 = (int((s(t * .35) + 1) / 2 * hw), int((c(t * .27) + 1) / 2 * hh))
        o2 = (int((c(t * .22 + 1) + 1) / 2 * hw), int((s(t * .31 + 2) + 1) / 2 * hh))
        a = self.t1.crop((o1[0], o1[1], o1[0] + hw, o1[1] + hh))
        b = self.t2.crop((o2[0], o2[1], o2[0] + hw, o2[1] + hh))
        k = self.strength
        m = ImageChops.add(a, b, 2.0).point(lambda v: min(255, max(0, v - 95) * 2) * k // 255).filter(ImageFilter.GaussianBlur(1.2))
        gl = Image.new("L", (hw, hh), 0)
        gl.paste(self.glare, (int(((t / 16) % 1) * 2 * hw - hw), (hh - self.glare.height) // 2))
        layer = Image.new("RGBA", (hw, hh), (175, 232, 255, 0))
        layer.putalpha(ImageChops.add(m, gl))
        return Image.alpha_composite(self.base if base is None else base, layer.resize((self.w, self.h), BIL))


# ---------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------
class Vaultek(tk.Tk):
    def __init__(self):
        super().__init__()
        antidebug()
        
        # Set up Taskbar Application Model ID for Windows icon binding
        if sys.platform == "win32":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("vaultek.credential.vault.1.0")
            except Exception:
                pass

        # Set Window / Taskbar Icon
        if os.path.exists(ICON_PATH):
            try:
                self.iconbitmap(ICON_PATH)
            except Exception:
                pass

        self.configure(bg=KEY)
        self.vault, self.q, self.imgs = Vault(), queue.Queue(), []
        self.data = norm({})
        self.loaded = self.saving = self.dirty = self.busy = False
        self.new_confirm = self.anim = self.assets = self.lc = None
        self.hover, self.shown, self.pw_items, self.hints = None, [], [], []
        self.ph_on, self.mode, self.t0, self.closing = True, "login", time.time(), False
        threading.Thread(target=self.prepare_main, daemon=True).start()   # builds the big glass UI while you type
        self.overrideredirect(True)                                       # small borderless login window
        try: self.attributes("-transparentcolor", KEY)
        except tk.TclError: pass
        self.place_window(LW, LH)
        self.canvas = tk.Canvas(self, width=LW, height=LH, highlightthickness=0, bd=0, bg=KEY)
        self.canvas.pack()
        self.bg_item = self.canvas.create_image(0, 0, anchor="nw")
        self.bind("<Escape>", lambda e: self.quit_app() if self.mode == "login" else None)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.pump()
        self.login()
        self.tick()

    # ---- plumbing ----
    def place_window(self, w, h):
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+{(self.winfo_screenheight() - h) // 2}")

    def quit_app(self):
        """Clean shutdown: stop timers, free images while Tk is alive, then hard-exit (avoids Tcl 'alloc: invalid block')."""
        if self.closing: return
        self.closing = True
        self.anim = None
        self.photo = self.backdrop = self.card_img = None
        self.imgs.clear()
        try: self.destroy()
        except tk.TclError: pass

    def prepare_main(self):
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))            # see-through frosted panes (no wallpaper)
        for box, kw in [((40, 28, 884, 84), dict(r=28, tint=(10, 40, 88), ta=185, gloss=35)),
                        ((40, 108, 940, 652), dict(r=22, tint=(8, 44, 104), ta=70, gloss=80))]:
            ov.alpha_composite(glass(None, box, **kw), (box[0] - PAD, box[1] - PAD))
        card = glass(None, (0, 0, CW, CH), r=16, tint=(20, 80, 160), ta=70, gloss=70)
        self.assets = (ov, card)

    def snapshot(self):
        """Blurred, blue-tinted copy of the desktop: the 'see-through' part of the frosted glass."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        try:
            im = ImageGrab.grab().convert("RGB").resize((sw, sh), BIL)
        except Exception:
            im = make_background(sw // 2, sh // 2, None).convert("RGB").resize((sw, sh), BIL)
        im = im.resize((max(1, sw // 6), max(1, sh // 6)), BIL).filter(ImageFilter.GaussianBlur(5)).resize((sw, sh), BIL)
        return Image.blend(im, Image.new("RGB", (sw, sh), (10, 48, 112)), .45).convert("RGBA")

    def run_bg(self, fn, cb):
        def work():
            try: r = fn()
            except Exception as e: r = ("error", str(e))
            self.q.put((cb, r))
        threading.Thread(target=work, daemon=True).start()

    def pump(self):
        if self.closing: return
        try:
            while True:
                cb, r = self.q.get_nowait()
                cb(r)
        except queue.Empty:
            pass
        self.after(80, self.pump)

    def render(self):
        if not self.anim: return
        t = time.time() - self.t0
        if self.mode == "login":
            img = Image.new("RGB", (LW, LH), (1, 2, 3))
            img.paste(self.anim.frame(t).convert("RGB"), (0, 0), self.lmask)
        else:
            x, y = self.winfo_rootx(), self.winfo_rooty()        # glass follows the window over the snapshot
            base = Image.alpha_composite(self.shot.crop((x, y, x + W, y + H)), self.overlay)
            img = self.anim.frame(t, base).convert("RGB")
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.itemconfig(self.bg_item, image=self.photo)
        if self.mode == "main" and self.lc is not None:
            self.backdrop = ImageTk.PhotoImage(img.crop((56, 120, 924, 640)))
            self.lc.itemconfig(self.lc_bg, image=self.backdrop)

    def tick(self):
        if self.closing: return
        self.render()
        self.after(30, self.tick)

    def entry(self, parent=None, **kw):
        o = dict(bg="#0a2858", fg="#eaf8ff", insertbackground="#8fe3ff", relief="flat", highlightthickness=1,
                 highlightbackground="#2e86c8", highlightcolor="#9fe6ff", font=("Segoe UI", 12))
        o.update(kw)
        return tk.Entry(parent or self.canvas, **o)

    def add_button(self, c, tag, x, y, w, h, text, cmd):
        n, hv = make_button(w, h, text), make_button(w, h, text, True)
        self.imgs += [n, hv]
        it = c.create_image(x, y, image=n, tags=("ui", tag))
        c.tag_bind(tag, "<Enter>", lambda e: (c.itemconfig(it, image=hv), c.config(cursor="hand2")))
        c.tag_bind(tag, "<Leave>", lambda e: (c.itemconfig(it, image=n), c.config(cursor="")))
        c.tag_bind(tag, "<Button-1>", lambda e: cmd())

    # ---- login (small glowing glass window) ----
    def login(self):
        self.mode = "login"
        base = glass(make_background(LW, LH), (0, 0, LW, LH), r=22, tint=(8, 44, 104), ta=70,
                     blur=6, gloss=90).crop((PAD, PAD, PAD + LW, PAD + LH))
        self.lmask = base.getchannel("A").point(lambda v: 255 if v > 127 else 0)
        self.anim = Shimmer(base, strength=130, scale=2)
        c = self.canvas
        c.create_text(180, 44, text="VAULTEK", font=("Segoe UI Light", 24), fill="#e8f7ff", tags="ui")
        self.pw = self.entry(show="•", font=("Segoe UI", 12), justify="center")
        c.create_window(180, 100, window=self.pw, width=260, height=32, tags="ui")
        self.pw.bind("<Return>", lambda e: self.unlock())
        self.add_button(c, "unlock", 180, 150, 130, 34, "UNLOCK", self.unlock)
        self.msg = c.create_text(180, 196, text="", font=("Segoe UI", 8), fill="#ff9aa8", tags="ui",
                                 width=320, justify="center")
        x = c.create_text(342, 18, text="✕", font=("Segoe UI", 10), fill="#bfe9ff", tags=("ui", "x"))
        c.tag_bind("x", "<Button-1>", lambda e: self.quit_app())
        c.tag_bind("x", "<Enter>", lambda e: c.itemconfig(x, fill="#ffffff"))
        c.tag_bind("x", "<Leave>", lambda e: c.itemconfig(x, fill="#bfe9ff"))
        c.bind("<ButtonPress-1>", lambda e: setattr(self, "_d", (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())))
        c.bind("<B1-Motion>", lambda e: self.mode == "login" and
               self.geometry(f"+{e.x_root - self._d[0]}+{e.y_root - self._d[1]}"))
        self.after(250, lambda: (self.focus_force(), self.pw.focus_set()))

    def say(self, t, col="#ff9aa8"):
        self.canvas.itemconfig(self.msg, text=t, fill=col)

    def unlock(self):
        pw = self.pw.get()
        if not pw or self.busy: return
        if not TOKEN: return self.say("No GitHub token set - see CONFIG at the top of vaultek.py")
        if self.new_confirm is not None:
            if pw != self.new_confirm:
                self.new_confirm = None
                self.pw.delete(0, "end")
                return self.say("Passwords didn't match. Start again.")
            self.busy = True
            self.say("Creating vault…", "#9fe0ff")
            return self.run_bg(lambda: self.vault.create(pw), lambda r: self.unlocked(r, pw))
        self.busy = True
        self.say("Decrypting…", "#9fe0ff")
        self.run_bg(lambda: self.vault.open(pw), lambda r: self.unlocked(r, pw))

    def unlocked(self, r, pw):
        self.busy = False
        if r[0] == "ok":
            self.new_confirm = None
            self.data = norm(r[1])
            self.data["devices"][PC] = now_iso()
            self.loaded = True
            self.show_main()
            self.save()
        elif r[0] == "new":
            self.new_confirm = pw
            self.pw.delete(0, "end")
            self.say("No vault found (or repo/token wrong). Type the password again to create one.", "#9fe0ff")
        elif r[0] == "wrong":
            self.pw.delete(0, "end")
            self.say("Wrong password")
        else:
            self.say(r[1])

    # ---- main window ----
    def show_main(self):
        if not self.assets:
            return self.after(100, self.show_main)
        self.overlay, card = self.assets
        self.card_img = ImageTk.PhotoImage(card)
        self.anim = None
        c = self.canvas
        self.withdraw()
        self.update()
        time.sleep(0.2)                                          # let the desktop repaint before the snapshot
        self.shot = self.snapshot()
        self.anim = Shimmer(self.overlay, strength=75, scale=3)
        self.mode = "main"
        self.overrideredirect(False)
        try: 
            self.attributes("-transparentcolor", "")
            self.attributes("-alpha", 0.88)
        except tk.TclError: pass
        self.title("Vaultek")
        
        # Ensure icon remains applied when exiting borderless login mode into main window
        if os.path.exists(ICON_PATH):
            try:
                self.iconbitmap(ICON_PATH)
            except Exception:
                pass

        self.configure(bg="#04122e")
        self.resizable(False, False)
        self.place_window(W, H)
        c.delete("ui")
        self.pw.destroy()
        c.unbind("<ButtonPress-1>")
        c.unbind("<B1-Motion>")
        c.config(width=W, height=H, bg="#04122e")
        self.deiconify()

        self.search = self.entry(font=("Segoe UI", 13), fg="#6aa6d4", highlightthickness=0, bd=0, bg="#081c3e")
        self.search.insert(0, PH)
        self.ph_on = True
        self.search.bind("<FocusIn>", self.s_in)
        self.search.bind("<FocusOut>", self.s_out)
        self.search.bind("<KeyRelease>", self.on_search)
        self.search_win = c.create_window(462, 56, window=self.search, width=780, height=30, tags="ui")
        self.add_button(c, "add", 928, 56, 50, 50, "+", self.add_modal)

        self.lc = tk.Canvas(c, width=868, height=520, highlightthickness=0, bd=0, yscrollincrement=30)
        self.lc_bg = self.lc.create_image(0, 0, anchor="nw")
        self.lc.configure(yscrollcommand=lambda *a: self.lc.coords(self.lc_bg, 0, self.lc.canvasy(0)))
        self.lc.bind("<MouseWheel>", lambda e: self.lc.yview_scroll(int(-e.delta / 120) * 2, "units"))
        self.lc.bind("<Motion>", lambda e: self.set_hover(self.index_at(e)))
        self.lc.bind("<Leave>", lambda e: self.set_hover(None))
        self.lc.bind("<Button-1>", self.on_click)
        self.lc.bind("<Button-3>", self.on_delete)
        self.lc_win = c.create_window(490, 380, window=self.lc, width=868, height=520, tags="ui")
        self.status = c.create_text(44, 684, anchor="sw", font=("Segoe UI", 7), fill="#5f9fd0", tags="ui", text="")
        self.dev = c.create_text(958, 684, anchor="se", font=("Segoe UI", 7), fill="#5f9fd0", tags="ui", text="")
        self.render()
        self.refresh_view()
        self.after(60000, self.refresh)

    def s_in(self, e):
        if self.ph_on:
            self.search.delete(0, "end")
            self.search.config(fg="#eaf8ff")
            self.ph_on = False

    def s_out(self, e):
        if not self.search.get():
            self.search.insert(0, PH)
            self.search.config(fg="#6aa6d4")
            self.ph_on = True

    def set_status(self, t):
        self.canvas.itemconfig(self.status, text=t)

    def update_devices(self):
        parts = [f"{PC} (this pc)"]
        for n, t in sorted(self.data["devices"].items(), key=lambda kv: kv[1], reverse=True):
            if n != PC:
                parts.append(f"{n} · {ago(t)}")
        self.canvas.itemconfig(self.dev, text="   |   ".join(parts[:4]))

    def refresh_view(self):
        self.update_devices()
        self.on_search()

    def on_search(self, e=None):
        q = "" if self.ph_on else self.search.get().strip().lower()
        items = sorted(self.data["entries"], key=lambda x: str(x.get("platform", "")).lower())
        if q and items:
            hay = lambda x: f"{x.get('platform', '')} {x.get('user', '')} {x.get('note', '')}".lower()
            hit = [x for x in items if q in hay(x)]
            rest = [x for x in items if x not in hit]
            if rest:
                res = process.extract(q, [str(x.get("platform", "")) for x in rest],
                                      scorer=fuzz.WRatio, limit=None, score_cutoff=70)
                hit += [rest[i] for _, _, i in res]
            items = hit
        self.draw_cards(items)

    def draw_cards(self, items):
        lc = self.lc
        lc.delete("card")
        self.shown, self.pw_items, self.hints, self.hover = items, [], [], None
        if not items:
            lc.create_text(434, 240, text="Nothing here yet. Press  +  to save a login.",
                           font=("Segoe UI", 12), fill="#cfeeff", tags="card")
        x0, mono = 9, ("Consolas", 11)
        for i, it in enumerate(items):
            y = 6 + i * (CH + GAP)
            lc.create_image(x0 - PAD, y - PAD, anchor="nw", image=self.card_img, tags="card")
            lc.create_text(x0 + 24, y + 12, anchor="nw", text=trunc(it.get("platform", ""), 40),
                           font=("Segoe UI Semibold", 15), fill="#ffffff", tags="card")
            lc.create_text(x0 + CW - 20, y + 16, anchor="ne", text=str(it.get("updatedAt", ""))[:16].replace("T", " "),
                           font=("Segoe UI", 8), fill="#9fd6f7", tags="card")
            lc.create_text(x0 + 24, y + 46, anchor="nw", text="user: " + trunc(it.get("user", "")),
                           font=mono, fill="#d6f1ff", tags="card")
            self.pw_items.append(lc.create_text(x0 + 24, y + 66, anchor="nw", text="pass: " + "•" * 10,
                                                font=mono, fill="#d6f1ff", tags="card"))
            lc.create_text(x0 + 24, y + 86, anchor="nw", text="note: " + trunc(it.get("note", "")),
                           font=mono, fill="#a9d8f5", tags="card")
            self.hints.append(lc.create_text(x0 + CW - 20, y + CH - 12, anchor="se",
                                             text="click to copy · right-click to delete",
                                             font=("Segoe UI", 7), fill="#8cc4ea", tags="card"))
        lc.configure(scrollregion=(0, 0, 868, max(520, 12 + len(items) * (CH + GAP))))
        lc.yview_moveto(0)
        lc.coords(self.lc_bg, 0, 0)

    def index_at(self, e):
        y = self.lc.canvasy(e.y) - 6
        if y < 0 or not (9 <= e.x <= 9 + CW): return None
        i, off = int(y // (CH + GAP)), y % (CH + GAP)
        return i if off < CH and i < len(self.shown) else None

    def set_hover(self, i):
        if i == self.hover: return
        if self.hover is not None and self.hover < len(self.pw_items):
            self.lc.itemconfig(self.pw_items[self.hover], text="pass: " + "•" * 10)
        if i is not None:
            self.lc.itemconfig(self.pw_items[i], text="pass: " + trunc(self.shown[i].get("pass", ""), 50))
        self.hover = i
        self.lc.config(cursor="hand2" if i is not None else "")

    def on_click(self, e):
        i = self.index_at(e)
        if i is None: return
        self.clipboard_clear()
        self.clipboard_append(str(self.shown[i].get("pass", "")))
        h = self.hints[i]
        self.lc.itemconfig(h, text="copied ✓", fill="#9fffd8")
        self.after(1300, lambda: self.lc.itemconfig(h, text="click to copy · right-click to delete", fill="#8cc4ea")
                   if h in self.hints else None)

    def on_delete(self, e):
        i = self.index_at(e)
        if i is None: return
        it = self.shown[i]
        if messagebox.askyesno("Vaultek", f"Delete the {it.get('platform', '')} login?"):
            self.data["entries"] = [x for x in self.data["entries"] if x.get("id") != it.get("id")]
            self.data["deleted"].append(it.get("id"))
            self.refresh_view()
            self.save()

    # ---- add entry (the + button) ----
    def add_modal(self):
        if not self.loaded or getattr(self, "modal_open", False): return
        self.modal_open = True
        c = self.canvas

        if hasattr(self, 'lc_win'): c.itemconfig(self.lc_win, state="hidden")
        if hasattr(self, 'search_win'): c.itemconfig(self.search_win, state="hidden")

        self.modal_dim = c.create_rectangle(0, 0, W, H, fill="#000714", stipple="gray50", tags="modal_ui")

        cx, cy = W // 2, H // 2
        
        modal_img = glass(None, (0, 0, 440, 500), r=24, tint=(12, 38, 85), ta=200, gloss=90, edge=(140, 225, 255))
        self.modal_ph = ImageTk.PhotoImage(modal_img)
        
        c.create_image(cx, cy, image=self.modal_ph, tags="modal_ui")
        c.create_text(cx, cy - 188, text="NEW LOGIN", font=("Segoe UI Light", 20), fill="#e8f7ff", tags="modal_ui")

        self.modal_ents = {}
        for n, (lab, key) in enumerate([("Platform", "platform"), ("Username", "user"),
                                        ("Password", "pass"), ("Note", "note")]):
            y = cy - 132 + n * 66
            c.create_text(cx - 168, y - 18, anchor="w", text=lab.upper(), font=("Segoe UI", 8, "bold"), fill="#8fd0f5", tags="modal_ui")
            e = self.entry(self, font=("Segoe UI", 11))
            c.create_window(cx, y + 4, window=e, width=336, height=32, tags="modal_ui")
            self.modal_ents[key] = e

        def close_modal():
            for ent in self.modal_ents.values():
                ent.destroy()
            c.delete("modal_ui")
            c.delete("modal_btn")
            self.modal_open = False
            
            if hasattr(self, 'lc_win'): c.itemconfig(self.lc_win, state="normal")
            if hasattr(self, 'search_win'): c.itemconfig(self.search_win, state="normal")

        def submit():
            if not self.modal_ents["platform"].get().strip(): return
            self.data["entries"].append({
                "id": str(int(time.time() * 1000)), "platform": self.modal_ents["platform"].get().strip(),
                "user": self.modal_ents["user"].get(), "pass": self.modal_ents["pass"].get(), "note": self.modal_ents["note"].get(),
                "updatedAt": now_iso()})
            self.refresh_view()
            if hasattr(self, "save"): self.save()
            close_modal()

        self.add_button(c, "modal_btn", cx, cy + 162, 200, 44, "SAVE", submit)
        
        x_btn = c.create_text(cx + 170, cy - 188, text="✕", font=("Segoe UI", 14), fill="#bfe9ff", tags="modal_ui")
        c.tag_bind(x_btn, "<Button-1>", lambda e: close_modal())
        c.tag_bind(x_btn, "<Enter>", lambda e: c.itemconfig(x_btn, fill="#ffffff"))
        c.tag_bind(x_btn, "<Leave>", lambda e: c.itemconfig(x_btn, fill="#bfe9ff"))

    # ---- sync ----
    def save(self):
        if not self.loaded: return
        self.data["devices"][PC] = now_iso()
        self.set_status("Saving...")
        self.run_bg(lambda: self.vault.push_merge(self.data), self.on_saved)

    def on_saved(self, r):
        if r[0] == "ok":
            self.data = r[1]
            self.set_status(f"Saved at {datetime.datetime.now().strftime('%H:%M:%S')}")
            self.refresh_view()
        else:
            self.set_status(f"Save failed: {r[1]}")

    def refresh(self):
        if self.loaded and not self.busy:
            self.run_bg(lambda: self.vault.pull(), self.on_refreshed)
        self.after(60000, self.refresh)

    def on_refreshed(self, r):
        if r[0] == "ok":
            self.data = merge(self.data, r[1])
            self.refresh_view()


if __name__ == "__main__":
    if "--mask" in sys.argv:
        try:
            t = sys.argv[sys.argv.index("--mask") + 1]
            print(f"PAT_MASKED = {[ord(c) ^ 0x7F for c in t]}")
        except IndexError:
            print("Usage: python vaultek.py --mask YOUR_TOKEN")
        sys.exit(0)
    app = Vaultek()
    app.mainloop()
