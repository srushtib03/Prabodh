import os
from dotenv import load_dotenv

load_dotenv() # This loads the .env file

import webbrowser
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from pydantic import BaseModel
import uvicorn
import google.generativeai as genai
from youtube_search import YoutubeSearch
import json
import sqlite3
import csv
import re  # Import regex for better cleaning

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            topic TEXT,
            status TEXT,
            feedback TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- CONFIGURATION ---
GENAI_API_KEY = os.getenv("GENAI_API_KEY")

genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('models/gemini-2.5-flash')

app = FastAPI()

class UserResponse(BaseModel):
    name: str = "Student"
    phone: str = "Unknown"
    topic: str
    user_answer: str = None
    mode: str 

# --- HELPER: BULLETPROOF JSON EXTRACTOR ---
def extract_json(text):
    """
    Finds the JSON object inside the text, even if the AI adds extra words.
    """
    try:
        # 1. Try finding content between curly braces { ... }
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        
        # 2. If no braces, try cleaning code blocks
        cleaned = text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except:
        return None

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("login.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/login-user")
async def login_user(name: str = Form(...), phone: str = Form(...), mode: str = Form(...)):
    return RedirectResponse(url=f"/index.html?mode={mode}&name={name}&phone={phone}", status_code=303)

@app.get("/index.html", response_class=HTMLResponse)
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/teacher", response_class=HTMLResponse)
async def read_teacher():
    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, phone, topic, status, feedback FROM student_data ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    with open("teacher.html", "r", encoding="utf-8") as f:
        html_template = f.read()
    
    table_html = ""
    for row in rows:
        table_html += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{row[3]}</td><td>{row[4]}</td></tr>"
    
    return HTMLResponse(content=html_template.replace("<tbody>", f"<tbody>{table_html}"))

@app.get("/api/download_records")
async def download_records():
    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, phone, topic, status, feedback FROM student_data")
    rows = cursor.fetchall()
    conn.close()

    file_path = "student_records.csv"
    with open(file_path, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Student Name", "Phone", "Topic Studied", "Status", "AI Feedback"])
        writer.writerows(rows)
    
    return FileResponse(path=file_path, filename="student_report.csv", media_type='text/csv')

# --- API ENDPOINTS ---

@app.post("/api/start_quiz")
async def start_quiz(data: UserResponse):
    prompt = f"Ask one simple question about '{data.topic}' for a Class 10 student."
    try:
        response = model.generate_content(prompt)
        question_text = response.text
    except:
        question_text = f"Tell me what you know about {data.topic}."
    return {"question": question_text}

@app.post("/api/submit_answer")
async def submit_answer(data: UserResponse):
    # 1. AI Analysis Prompt
    prompt = (f"Analyze: Topic:{data.topic}, Ans:{data.user_answer}. "
              "Return JSON: {'correct':true, 'explanation':'SHORT feedback', 'search_query':'topic keywords'}")
    
    analysis = None
    try:
        response = model.generate_content(prompt)
        # 2. USE NEW BULLETPROOF EXTRACTOR
        analysis = extract_json(response.text)
    except Exception as e:
        print(f"AI Error: {e}")

    # 3. Fallback if extraction failed
    if not analysis:
        analysis = {
            "correct": False, 
            "explanation": "Could not analyze answer. Please try again.", 
            "search_query": data.topic
        }

    # 4. Save to Database
    conn = sqlite3.connect('records.db')
    cursor = conn.cursor()
    status = "Correct" if analysis.get("correct") else "Needs Review"
    cursor.execute("INSERT INTO student_data (name, phone, topic, status, feedback) VALUES (?, ?, ?, ?, ?)",
                   (data.name, data.phone, data.topic, status, analysis.get("explanation")))
    conn.commit()
    conn.close()

    # 5. Get Video
    query = analysis.get('search_query', data.topic)
    try:
        results = YoutubeSearch(query, max_results=1).to_dict()
        video_id = results[0]['id'] if results else "dQw4w9WgXcQ"
    except:
        video_id = "dQw4w9WgXcQ"

    return {"analysis": analysis, "video_id": video_id}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)