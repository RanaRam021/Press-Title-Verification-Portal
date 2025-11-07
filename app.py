from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import pandas as pd
import json
import os
from fuzzywuzzy import fuzz
from metaphone import doublemetaphone
from nltk.corpus import stopwords, wordnet
import nltk
import re
import random
from langchain_google_genai import ChatGoogleGenerativeAI
import ast


llm = ChatGoogleGenerativeAI(model = 'gemini-2.0-flash' , temperature = 0.6 , api_key = GOOGLE_API)

nltk.download('stopwords')
nltk.download('wordnet')

app = Flask(__name__)
app.secret_key = 'fdffuj@$$dhfur465647gfg'

ADMIN_PASSWORD = "admin123"
DATA_FILE = "New_Dataset.csv"
USER_FILE = "users.json"
PENDING_FILE = "pending_titles.json"

stop_words = set(stopwords.words('english'))

if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE)
    titles_db = set(df['Title Name'].str.lower().str.strip())
else:
    df = pd.DataFrame(columns=['Title Name', 'Owner Name', 'State', 'District'])
    titles_db = set()

# Rules
stop_words = set(stopwords.words('english'))
disallowed_words = {"police", "crime", "corruption", "cbi", "cid", "army"}
disallowed_prefixes = {"the", "india", "samachar", "news"}
disallowed_suffixes = {"daily", "weekly", "monthly"}

# Helpers
def preprocess_title(title):
    title = title.lower().strip()
    title = re.sub(r'[^a-zA-Z0-9\s]', '', title)
    return ' '.join([word for word in title.split() if word not in stop_words])

def check_similarity(new_title):
    clean = preprocess_title(new_title)
    phonetic = doublemetaphone(clean)
    for title in titles_db:
        if fuzz.ratio(clean, title) > 80 or doublemetaphone(title)[0] == phonetic[0]:
            return True, title
    return False, None

def check_rules(new_title):
    words = set(new_title.lower().split())
    if words & disallowed_words:
        return False, "Contains disallowed words"
    if any(new_title.lower().startswith(prefix) for prefix in disallowed_prefixes):
        return False, "Contains disallowed prefix"
    if any(new_title.lower().endswith(suffix) for suffix in disallowed_suffixes):
        return False, "Contains disallowed suffix"
    return True, "Valid title"

def verification_probability(new_title):
    clean = preprocess_title(new_title)
    max_sim = max([fuzz.ratio(clean, title) for title in titles_db], default=0)
    return 100 - max_sim

def suggest_titles(base_title, max_suggestions=5):
    base_words = [word for word in base_title.lower().split() if word not in stop_words]

    for i in base_words:
        if i in disallowed_words:
            base_words.remove(i)
            
    suggestions = set()
   


    while len(suggestions) < max_suggestions:

        prompt = f'''suggest 7 alternative and similar names for {base_title} newspaper.

                    names should not contain {disallowed_words} words, {disallowed_prefixes} prefixes and {disallowed_suffixes} suffixes.
                    write name in a list like ['name1', 'name2', 'name3'] '''
                
        ans = llm.invoke(prompt)
        ans1 = ans.content.strip()


        match = re.search(r"\[.*\]", ans1, re.DOTALL)
        if match:
            titles_list = ast.literal_eval(match.group())
        else:
            titles_list = []

        for i in titles_list:
            clean_combined = preprocess_title(i)
            is_similar, _ = check_similarity(clean_combined)
            is_valid, reason = check_rules(clean_combined)
            if is_valid and not is_similar and clean_combined not in titles_db:
                suggestions.add(i)
    return list(suggestions)



# Routes
@app.route('/')
def homepage():
    return render_template('home.html')

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_panel'))
        else:
            return "incorrect Password!"
    return render_template('login.html', admin=True)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if os.path.exists(USER_FILE):
            with open(USER_FILE, 'r') as f:
                users = json.load(f)
        else:
            users = {}
        username = request.form['username']
        password = request.form['password']
        if users.get(username) == password:
            session['username'] = username
            return redirect(url_for('index'))
        
        else:
            return "Username or Password is incorrect!"
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    data = request.form
    username, password = data['username'], data['password']
    users = {}
    if os.path.exists(USER_FILE):
        with open(USER_FILE, 'r') as f:
            users = json.load(f)
    if username not in users:
        users[username] = password
        with open(USER_FILE, 'w') as f:
            json.dump(users, f)
        session['username'] = username
        return redirect(url_for('index'))
    return "Username exists!"

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('homepage'))

@app.route('/index')
def index():
    if 'username' in session:
        return render_template('index.html', username=session['username'])
    return redirect(url_for('login'))

@app.route('/admin')
def admin_panel():
    if session.get('admin'):
        if os.path.exists(PENDING_FILE):
            with open(PENDING_FILE, 'r') as f:
                pending = json.load(f)
        else:
            pending = []
        return render_template('admin.html', pending=pending)
    return redirect(url_for('admin_login'))

@app.route('/verify', methods=['POST'])
def verify():
    title = request.json.get("title")

    is_valid, reason = check_rules(title)
    if not is_valid:
        suggestions = suggest_titles(title)
        return jsonify({
            "status": "Rejected",
            "reason": reason,
            "suggestions": suggestions
        })
    
    similar, existing = check_similarity(title)
    if similar:
        return jsonify({
            "status": "Rejected",
            "reason": f"Too similar to '{existing}'",
            "suggestions": suggest_titles(title)
        })
    
    

    score = verification_probability(title)

    return jsonify({
        "status": "Verified",
        "verification_probability": f"{score:.2f}%",
        "suggestions": [],
        "title": title,
        "score": f"{score:.2f}"
    })

@app.route('/submit', methods=['POST'])
def submit():

    try:
        data = request.get_json(force=True)
        print("Received data:", data)
    
        title = data.get("title")
        score_str = data.get('score', '0').replace('%', '')  # Remove '%' before converting
        score = float(score_str) 
        owner = data.get("owner")
        state = data.get("state")
        district = data.get("district")

        if not all([title, score, owner, state, district]):
            print("Received:", title, score, owner, state, district)

            return jsonify({"status": "Error", "message": "Missing fields"}), 400

        if os.path.exists(PENDING_FILE):
            with open(PENDING_FILE, 'r') as f:
                pending = json.load(f)
        else:
            pending = []

        pending.append({
            "title": title,
            "score": f"{float(score):.2f}",
            "owner_name": owner,
            "state": state,
            "district": district
        })

        with open(PENDING_FILE, 'w') as f:
            json.dump(pending, f, indent=2)

        return jsonify({"status": "Submitted", "message": "Title submitted for review."})
    
    except Exception as e:
        print("Error:", e)
        return jsonify({'message': 'Failed to parse JSON'}), 400

@app.route('/accept-title', methods=['POST'])
def accept_title():
    title = request.form['title']
    owner = request.form.get('owner', '')
    state = request.form.get('state', '')
    district = request.form.get('district', '')

    print("Received:", title, owner, state, district)
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
    else:
        df = pd.DataFrame(columns=['Title Name', 'Owner Name', 'State', 'District'])


    df = pd.concat([df, pd.DataFrame([{
        'Title Name': title,
        'Owner Name': owner,
        'State': state,
        'Publication City/District': district
    }])], ignore_index=True)

    df.to_csv(DATA_FILE, index=False)
    titles_db.add(title.lower().strip())

    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r') as f:
            pending = json.load(f)
        pending = [t for t in pending if t['title'] != title]
        with open(PENDING_FILE, 'w') as f:
            json.dump(pending, f, indent=2)

    return redirect(url_for('admin_panel'))

@app.route('/reject-title', methods=['POST'])
def reject_title():
    title = request.form['title']
    
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r') as f:
            pending = json.load(f)
        pending = [t for t in pending if t['title'] != title]
        with open(PENDING_FILE, 'w') as f:
            json.dump(pending, f, indent=2)

    return redirect(url_for('admin_panel'))

if __name__ == '__main__':
    app.run(debug=True)
