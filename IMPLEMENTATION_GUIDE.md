## Local V2 privacy-first workflow

This version now performs local parsing and regex-based redaction before any optional external LLM call. External LLM use is off by default in the frontend. When enabled, only redacted text plus structured grant facts are eligible to leave the local app.

# Implementation Guide: Run the Grant Automation Agent Locally on a Mac

This guide is written for a beginner using the **Terminal** app on macOS.

## 1. What you need before you start

Install these first:

- **Python 3.11 or 3.12**
- **Node.js 20 LTS or newer**
- an **OpenAI API key**

### Check whether Python is installed
Open **Terminal** and run:

```bash
python3 --version
```

You should see something like `Python 3.11.x` or `Python 3.12.x`.

### Check whether Node is installed
In Terminal, run:

```bash
node --version
npm --version
```

You should see version numbers for both commands.

## 2. Unzip the project

Put the project folder somewhere easy to find, such as your Desktop or Documents folder.

Then in Terminal, move into the project folder. Example:

```bash
cd ~/Desktop/grant-automation-agent-main
```

Use the actual folder path on your Mac.

## 3. Set up the backend

### Step 3.1: move into the backend folder

```bash
cd backend
```

### Step 3.2: create a virtual environment

```bash
python3 -m venv .venv
```

### Step 3.3: activate the virtual environment

```bash
source .venv/bin/activate
```

After activation, your Terminal line should begin with something like `(.venv)`.

### Step 3.4: install backend packages

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3.5: create the backend environment file

Copy the example file:

```bash
cp .env.example .env
```

Open it in TextEdit:

```bash
open -a TextEdit .env
```

Then paste your OpenAI API key after `OPENAI_API_KEY=`.

Example:

```env
OPENAI_API_KEY=your_real_key_here
HOST=localhost
PORT=8000
DEMO_MODE=false
```

If you want to test the app without calling OpenAI yet, set:

```env
DEMO_MODE=true
```

That will return mock data instead of making a live API call.

### Step 3.6: start the backend

```bash
uvicorn app.main:app --reload
```

If the backend starts correctly, you should see a message showing that it is running on `http://127.0.0.1:8000` or `http://localhost:8000`.

### Step 3.7: verify the backend is working

Open this in your browser:

- `http://localhost:8000/health`
- `http://localhost:8000/docs`

If you see the health response and the API docs page, the backend is working.

## 4. Set up the frontend

Open a **new Terminal window or tab** so the backend can keep running.

### Step 4.1: move into the frontend folder

```bash
cd ~/Desktop/grant-automation-agent-main/frontend
```

### Step 4.2: install frontend packages

```bash
npm install
```

### Step 4.3: create the frontend environment file

```bash
cp .env.example .env
```

The default file already points to the local backend:

```env
VITE_API_URL=http://localhost:8000
```

### Step 4.4: start the frontend

```bash
npm run dev
```

Vite will print a local address, usually:

- `http://localhost:5173`

Open that in your browser.

## 5. How to use the app locally

1. Open the frontend in your browser.
2. Upload a **proposal**, an **award letter**, or both.
3. Wait for the extraction step to finish.
4. Review the generated grant details page.
5. Click the document generation options you want.
6. Download the generated files.

## 6. If something goes wrong

### Backend command not found
Try this instead:

```bash
python3 -m uvicorn app.main:app --reload
```

### Port 8000 is already in use
Change the backend port in `backend/.env`, for example:

```env
PORT=8001
```

If you change the backend port, also update the frontend `.env` file:

```env
VITE_API_URL=http://localhost:8001
```

Then restart both backend and frontend.

### Node modules act strangely
From the `frontend` folder, run:

```bash
rm -rf node_modules package-lock.json
npm install
```

### Python packages act strangely
From the `backend` folder, run:

```bash
deactivate
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 7. What is already cleaned up in this version

This version includes:

- separate upload fields for **proposal** and **award letter**
- a working **delete grant** action used by the frontend
- cleaned environment files with placeholders instead of embedded secrets
- a frontend build that compiles successfully after dependency install

## 8. What you need in order to get strong frontend help

To get useful support on the frontend, especially for **look and feel**, **UX**, and **UI**, it helps to provide these items:

### Minimum helpful inputs

- screenshots of the current app
- the exact screens you want improved
- examples of websites or apps whose design you like
- your preferred tone: formal, nonprofit, enterprise, modern, lightweight, etc.
- your main user types: grants manager, finance staff, executive director, program officer, and so on

### Even better inputs

- logo, colors, fonts, or brand guide
- a list of top user tasks in priority order
- pain points such as “too much text,” “confusing uploads,” or “hard to tell what to click next”
- mobile vs desktop expectations
- accessibility expectations, such as contrast, larger text, or keyboard navigation

### Best way to request frontend work

A strong request looks like this:

> Improve the home page and grant details page for a nonprofit operations audience. Make it feel more professional and less developer-oriented. Use clear step-by-step guidance, stronger visual hierarchy, and a calmer color palette. Here are screenshots of the current UI and two products I like.

That gives enough direction to help with:

- layout changes
- button hierarchy
- spacing and typography
- upload flow clarity
- dashboard structure
- color and branding suggestions
- UX copy

## 9. Useful local commands

### Start backend

```bash
cd ~/Desktop/grant-automation-agent-main/backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

### Start frontend

```bash
cd ~/Desktop/grant-automation-agent-main/frontend
npm run dev
```

### Stop either server
Press:

```bash
Control + C
```
