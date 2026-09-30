#  vaultek-app 
A windows application that can be used as a password manager (main purpose) or secure notes.
As i usually change browsers i find myself exporting my passwords every now and then.
And with frequent data breaches nowadays I've been thinking of a way to save my passwords somehow 
and a reliable way was to make an application of my own to do just that.
Vaultek here does that exactly 

-----------------------

# visual
<img width="685" height="522" alt="image" src="https://github.com/user-attachments/assets/4edea479-5993-4c95-8438-33a119fee089" />


<img width="996" height="758" alt="image" src="https://github.com/user-attachments/assets/0f4a0acb-c86a-4b1e-99b9-9b1042323a86" />


-----------------------
# Features

- **client-Side Encryption:** Uses `scrypt` for key derivation and `AES-256-GCM` to ensure your data is fully encrypted before it touches the cloud.
- **GitHub Sync:** Automatically syncs your encrypted vault data directly to a private GitHub repository and you can access it from any device the app in configured on. The data is scrambled so it is not readable from github moreover since the repo is private thats much more secure.
- **Built to give windows 7 vibes:** I'm not sure why.
- **Fuzzy Search:** Not too organized but easily search anything u saved 
- **log-in pass:** it asks for a password when you first open it. Typing in the password twice confirms it and that is your password from then on (I believe on that device) *not tested in a second device*

---------------------
   **How to set it up :** 
> in the config
  - **Username/Repo-name (change it to be your user and repo)**

  - **PAT_PLAIN  (put your GITHUB repo api here with read and write permissions for 'content')**

  - **Finally package it using `Nuitka` (recommended)**
  
  
that is mostly it 

---------------------

also!!
note that As i just started out with python it is of course *vibe coded*✌️
