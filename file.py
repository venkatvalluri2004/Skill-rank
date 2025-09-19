from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF for PDF extraction
import sqlite3
import openai
import os
import uuid

# Flask application setup
app = Flask(__name__)

# Initialize SQLite DB with tables for papers, summaries, and gaps
def init_db():
    with sqlite3.connect('papers.db') as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS papers
            (id INTEGER PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT, content TEXT, filename TEXT)
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS summaries
            (paper_id INTEGER, summary TEXT)
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS gaps
            (paper_id INTEGER, gaps TEXT)
        ''')
        conn.commit()

init_db()

# Extract text and metadata from PDF
def extract_content_from_pdf(file_path):
    doc = fitz.open(file_path)
    full_text = []
    metadata = doc.metadata
    for page in doc:
        full_text.append(page.get_text())
    content = '\n'.join(full_text)
    title = metadata.get('title', 'Unknown Title')
    authors = metadata.get('author', 'Unknown Authors')

    # Simple heuristic to extract abstract text
    lower_content = content.lower()
    abs_start = lower_content.find('abstract')
    abstract = ''
    if abs_start != -1:
        abs_end = lower_content.find('\n\n', abs_start + 8)
        abstract = content[abs_start + 8:abs_end].strip()
    return title, authors, abstract, content

# Endpoint to upload paper
@app.route('/upload', methods=['POST'])
def upload_paper():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']

    # The original filename is available here from the client's request
    original_filename = file.filename
    
    if original_filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and original_filename.endswith('.pdf'):
        # Generate a secure filename to prevent security issues and overwrites
        secure_name = secure_filename(original_filename)
        unique_name = f"{uuid.uuid4()}_{secure_name}"
        
        file_path = os.path.join('uploads', unique_name)
        os.makedirs('uploads', exist_ok=True)
        file.save(file_path)
        
        title, authors, abstract, content = extract_content_from_pdf(file_path)
        
        with sqlite3.connect('papers.db') as conn:
            c = conn.cursor()
            # The secure filename is now inserted into the database along with the other data
            c.execute('INSERT INTO papers (title, authors, abstract, content, filename) VALUES (?, ?, ?, ?, ?)',
                      (title, authors, abstract, content, original_filename))
            conn.commit()
            paper_id = c.lastrowid
            
        return jsonify({'paper_id': paper_id, 'title': title, 'authors': authors, 'abstract': abstract, 'filename': original_filename}), 200
    else:
        return jsonify({'error': 'Invalid file type'}), 400

# LLM summarization function (using OpenAI GPT-4)
# Note: You need to set your OPENAI_API_KEY environment variable.
openai.api_key = os.getenv('OPENAI_API_KEY')
def llm_summarize(content):
    prompt = (
        "Summarize this research paper content. Extract key findings, main contributions, "
        "research methodology, and results in bullet points:\n\n" + content)
    
    # In a real application, you would handle cases where the API key is not set.
    if not openai.api_key:
        return "LLM service not configured."
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        return response.choices[0].message['content']
    except Exception as e:
        return f"An error occurred: {str(e)}"

# Endpoint for summarization
@app.route('/summarize/<int:paper_id>', methods=['GET'])
def summarize_paper(paper_id):
    with sqlite3.connect('papers.db') as conn:
        c = conn.cursor()
        c.execute('SELECT content FROM papers WHERE id=?', (paper_id,))
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'Paper not found'}), 404
        content = row[0]
    summary = llm_summarize(content)
    with sqlite3.connect('papers.db') as conn:
        c = conn.cursor()
        c.execute('INSERT INTO summaries (paper_id, summary) VALUES (?, ?)', (paper_id, summary))
        conn.commit()
    return jsonify({'summary': summary}), 200

# LLM function for research gap analysis
def llm_research_gap_analysis(content):
    prompt = (
        "Identify the research limitations, gaps, potential future work, "
        "and unexplored opportunities in the following paper content:\n\n" + content)
    
    # In a real application, you would handle cases where the API key is not set.
    if not openai.api_key:
        return "LLM service not configured."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        return response.choices[0].message['content']
    except Exception as e:
        return f"An error occurred: {str(e)}"

# Endpoint for research gap analysis
@app.route('/gap_analysis/<int:paper_id>', methods=['GET'])
def gap_analysis(paper_id):
    with sqlite3.connect('papers.db') as conn:
        c = conn.cursor()
        c.execute('SELECT content FROM papers WHERE id=?', (paper_id,))
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'Paper not found'}), 404
        content = row[0]
    gaps = llm_research_gap_analysis(content)
    with sqlite3.connect('papers.db') as conn:
        c = conn.cursor()
        c.execute('INSERT INTO gaps (paper_id, gaps) VALUES (?, ?)', (paper_id, gaps))
        conn.commit()
    return jsonify({'gaps': gaps}), 200

@app.route('/')
def home():
    return "Flask app is running!"

# Endpoint for searching papers by keyword
@app.route('/search', methods=['GET'])
def search_papers():
    keyword = request.args.get('keyword', '').lower()
    if not keyword:
        return jsonify([])

    with sqlite3.connect('papers.db') as conn:
        c = conn.cursor()
        # Search across title, authors, abstract, and content
        c.execute("""
            SELECT id, title, authors, abstract
            FROM papers
            WHERE lower(title) LIKE ? OR lower(authors) LIKE ? 
               OR lower(abstract) LIKE ? OR lower(content) LIKE ?
        """, (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'))
        rows = c.fetchall()

    results = [
        {"paper_id": row[0], "title": row[1], "authors": row[2], "abstract": row[3]}
        for row in rows
    ]
    return jsonify(results)




if __name__ == '__main__':
    app.run(debug=True)
