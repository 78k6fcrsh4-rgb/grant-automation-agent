## Local V2 privacy-first workflow

This version now performs local parsing and regex-based redaction before any optional external LLM call. External LLM use is off by default in the frontend. When enabled, only redacted text plus structured grant facts are eligible to leave the local app.

# Grant Automation Agent

Grant Automation Agent is a local full-stack app that turns a grant proposal and/or award letter into a structured post-award management package. It extracts core grant details, builds a work plan, creates a budget workbook, generates a reporting template, creates a status meeting agenda, and exports calendar reminders as ICS files.

## Stack

- **Backend:** FastAPI, Python, LangChain, OpenAI
- **Frontend:** React, TypeScript, Vite, Tailwind CSS
- **Outputs:** PDF, DOCX, XLSX, ICS

## What the app does

- accepts a **proposal** file, an **award letter** file, or both
- extracts timeline, budget, work plan, reporting, and submission requirements
- generates:
  - work plan PDF
  - budget workbook XLSX
  - reporting template DOCX
  - status meeting agenda DOCX
  - calendar file ICS

## Quick start

Read **IMPLEMENTATION_GUIDE.md** for a Mac-friendly step-by-step setup.

## Environment files

Create these from the example files before running locally:

- `backend/.env.example` → `backend/.env`
- `frontend/.env.example` → `frontend/.env`

## Default local URLs

- Backend: `http://localhost:8000`
- Backend docs: `http://localhost:8000/docs`
- Frontend: `http://localhost:5173`
