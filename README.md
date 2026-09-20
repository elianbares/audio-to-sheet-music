# AI Audio to Sheet Music Generator

Upload a recording of someone playing solo piano or singing, and this app turns it into real sheet music you can
download as a **PDF**, a **MusicXML** file (for programs like MuseScore or Finale), and a **MIDI** file.

This guide assumes you have never used GitHub, a terminal, or deployed a website before. Every step tells you
exactly where to click and what to type. It will take about 15-20 minutes the first time.

---

## What this app actually does

1. You upload an MP3, WAV, or M4A recording.
2. An AI model called **Basic Pitch** (made by Spotify) listens to it and guesses which notes were played.
3. The app cleans up the timing so the notes line up into readable rhythm (quarter notes, eighth notes, rests, etc).
4. A music-notation program called **LilyPond** draws the actual sheet music.
5. You get a PDF you can print, plus MusicXML and MIDI files for further editing in other software.

**Important honesty note:** this is automatic transcription, not magic. It works best on a single clear instrument
or voice. It will make mistakes on complex or noisy recordings -- treat the result as a strong first draft, not a
perfect copy.

---

## Part 1 -- Put this project on GitHub

GitHub is a free website that stores your code and connects to Streamlit (the site that will actually run your
app for you, for free).

### Step 1: Create a GitHub account (skip if you already have one)

1. Go to **github.com**.
2. Click **Sign up** in the top right.
3. Follow the prompts (email, password, username). Verify your email if asked.

### Step 2: Create a new, empty repository

A "repository" (or "repo") is just a project folder that lives on GitHub.

1. Once logged in, click the **+** icon in the top right corner, then click **New repository**.
2. **Repository name:** type `audio-to-sheet-music` (or any name you like).
3. Leave it set to **Public**.
4. Do **not** check any of the boxes for "Add a README," "Add .gitignore," or "Choose a license" -- leave them
   unchecked.
5. Click the green **Create repository** button.
6. You'll land on a page with setup instructions and a URL like
   `https://github.com/your-username/audio-to-sheet-music.git`. Keep this tab open -- you'll need that URL in a
   moment.

### Step 3: Install Git on your computer (skip if `git` already works)

Git is the tool that uploads ("pushes") files from your computer to GitHub.

- **Mac:** Open the **Terminal** app (search for it with Spotlight: press `Cmd + Space`, type `Terminal`, press
  Enter). Type `git --version` and press Enter. If it prints a version number, you already have it. If it asks to
  install "Command Line Developer Tools," click **Install** and wait for it to finish.
- **Windows:** Download and install Git from **git-scm.com/download/win** (use all default options during
  install). Afterwards, open **Git Bash** from your Start menu -- that's the terminal you'll use below.

Tell Git who you are (only needed once per computer). Replace the name and email with your own, then run these
two lines one at a time:

```
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### Step 4: Upload this project to your new GitHub repository

Open your terminal (Terminal on Mac, Git Bash on Windows) and navigate into this project folder. If this folder
is at, for example, `Desktop/ArnellCoding/audio-to-sheet-music`, type:

```
cd Desktop/ArnellCoding/audio-to-sheet-music
```

Then copy and paste these commands **one at a time**, pressing Enter after each one. Replace the URL in the
`git remote add origin` line with the URL GitHub showed you in Step 2.

```
git init
git add app.py pipeline.py requirements.txt packages.txt runtime.txt README.md .gitignore .streamlit dev
git commit -m "Initial version of AI Audio to Sheet Music Generator"
git branch -M main
git remote add origin https://github.com/your-username/audio-to-sheet-music.git
git push -u origin main
```

If it asks you to log in, follow the on-screen prompts (a browser window may pop up asking you to authorize Git).

**What you should see:** refresh your GitHub repository page in your browser -- your files (`app.py`,
`pipeline.py`, etc.) should now appear there.

---

## Part 2 -- Deploy it for free on Streamlit Community Cloud

Streamlit Community Cloud is a free hosting service made specifically for apps like this one.

### Step 1: Sign up

1. Go to **share.streamlit.io**.
2. Click **Continue with GitHub** and log in with the same GitHub account from Part 1. Authorize Streamlit when
   asked.

### Step 2: Create the app

1. Click **Create app** (or **New app**).
2. Choose **"Deploy a public app from GitHub."**
3. Fill in the form:
   - **Repository:** pick `your-username/audio-to-sheet-music` from the dropdown.
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **"Advanced settings..."** before deploying, and set the **Python version** dropdown to **3.10**. This
   matters: it makes the AI model use a much lighter, faster mode that fits comfortably in Streamlit's free tier.
   (If 3.10 isn't offered, the included `runtime.txt` file will request it automatically.)
5. Click **Deploy**.

### Step 3: Wait

Streamlit will now install everything the app needs (this is what a `requirements.txt` and `packages.txt` file
are for -- think of them as an ingredients list Streamlit reads automatically). The first deploy takes **5-10
minutes** because it has to download the AI model and the sheet-music renderer. You'll see a log scrolling by --
that's normal. When it's done, your app opens automatically at a URL like:

```
https://your-username-audio-to-sheet-music.streamlit.app
```

That's it -- share that link with anyone, they don't need to install anything.

---

## How to update the app later

Whenever you (or I) change any file in this project and want the live app to reflect it:

```
git add -A
git commit -m "Describe what changed"
git push
```

Streamlit automatically notices the update and redeploys within a minute or two -- you don't need to touch the
Streamlit website again.

---

## Testing it

1. Open your deployed app link (or run it locally -- see below).
2. Upload a short (10-30 second) recording of a solo piano melody or someone singing a simple tune, clearly and
   without much background noise.
3. Click **Generate Sheet Music**.
4. Watch the progress messages, then check the PDF preview and try the three download buttons.

### Running it on your own computer first (optional but recommended)

If you want to test before deploying:

```
cd Desktop/ArnellCoding/audio-to-sheet-music
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

You'll also need LilyPond and ffmpeg installed locally (on Mac with Homebrew: `brew install lilypond ffmpeg`; on
Windows/Linux, download LilyPond from lilypond.org and ffmpeg from ffmpeg.org). On Streamlit Community Cloud you
don't need to do this -- `packages.txt` installs them automatically.

---

## Common errors and fixes

**"Error installing requirements" during Streamlit deploy**
Open the deploy log (there's a "Manage app" button in the bottom right of your app while it's running) and look
for the red error text. Usually this means a package version conflict -- copy the error and ask for help fixing
`requirements.txt`.

**The app deploys but crashes immediately / shows "Oh no."**
Click **"Manage app"** in the bottom right corner of the app page to see the full error log. The most common
cause is `packages.txt` not being picked up -- make sure that file is spelled exactly `packages.txt` (not
`.txt.txt` or `Packages.txt`) and sits in the main project folder, not a subfolder.

**"We couldn't detect a clear melody or instrument"**
The recording was silent, too short, or too noisy/complex for the AI to find a clear melody line. Try a cleaner,
simpler recording.

**"We couldn't read that file"**
The uploaded file isn't a valid MP3, WAV, or M4A (for example, it was renamed from a different file type). Try
re-exporting or re-recording it.

**The PDF preview doesn't show up in the browser, but the download button works**
Some mobile browsers don't display PDFs inline. Use the **Download PDF** button instead -- the file itself is
fine.

**My push to GitHub was rejected / asked for a username and password**
GitHub no longer accepts plain passwords for `git push`. When prompted, use a **Personal Access Token** instead
of your password (GitHub will guide you to create one at Settings -> Developer settings -> Personal access
tokens), or install **GitHub Desktop** (desktop.github.com) for a point-and-click alternative to the commands in
Part 1.

---

## Known limitations (please read)

- Works best on **one instrument or voice at a time** -- not full bands or mixed recordings.
- Struggles with heavy background noise, reverb, very fast passages, and strong vibrato.
- Tempo, key, and time signature are the app's best *guess* -- when it isn't confident, it simply hides that
  detail rather than showing a wrong guess.
- Recordings longer than 90 seconds are automatically trimmed to keep the free hosting tier responsive.
- This is never going to be 100% accurate. No automatic transcription tool is.
