from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import pandas as pd
import threading
import time
from scraper import run_scraper
import uuid
from datetime import timedelta
import hashlib

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))
app.config.update(
    UPLOAD_FOLDER='data',
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_COOKIE_SECURE=False,  # 개발 환경에서는 False
    SESSION_COOKIE_SAMESITE='Lax'
)

# CSRF 토큰 생성 함수
def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = hashlib.sha256(os.urandom(24)).hexdigest()
    return session['csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

scraping_jobs = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_scraping', methods=['POST'])
def start_scraping():
    # CSRF 토큰 검증
    if request.form.get('csrf_token') != session.get('csrf_token'):
        flash('잘못된 요청입니다.')
        return redirect(url_for('index'))

    keyword = request.form.get('keyword')
    max_channels = request.form.get('max_channels')
    
    if not keyword or not max_channels:
        flash('검색어와 채널 수를 모두 입력해주세요.')
        return redirect(url_for('index'))
    
    try:
        max_channels = int(max_channels)
        if max_channels <= 0:
            flash('채널 수는 양수여야 합니다.')
            return redirect(url_for('index'))
    except ValueError:
        flash('채널 수는 숫자여야 합니다.')
        return redirect(url_for('index'))
    
    job_id = str(uuid.uuid4())
    scraping_jobs[job_id] = {
        'status': '진행 중',
        'progress': 0,
        'keyword': keyword,
        'max_channels': max_channels,
        'result_file': None
    }
    
    thread = threading.Thread(
        target=run_scraper_thread,
        args=(job_id, keyword, max_channels)
    )
    thread.daemon = True
    thread.start()
    
    session['job_id'] = job_id
    session.modified = True
    return redirect(url_for('scraping_status'))

def run_scraper_thread(job_id, keyword, max_channels):
    try:
        result_file = run_scraper(keyword, max_channels, job_id, progress_callback)
        scraping_jobs[job_id]['status'] = '완료'
        scraping_jobs[job_id]['result_file'] = result_file
    except Exception as e:
        scraping_jobs[job_id]['status'] = '오류'
        scraping_jobs[job_id]['error'] = str(e)

def progress_callback(job_id, current, total):
    if job_id in scraping_jobs:
        scraping_jobs[job_id]['progress'] = int((current / total) * 100)

@app.route('/status')
def scraping_status():
    job_id = session.get('job_id')
    if not job_id or job_id not in scraping_jobs:
        flash('스크래핑 작업을 찾을 수 없습니다.')
        return redirect(url_for('index'))
    
    job = scraping_jobs[job_id]
    return render_template('status.html', job=job)

@app.route('/get_status')
def get_status():
    job_id = request.args.get('job_id') or session.get('job_id')
    if not job_id:
        return jsonify({'status': 'error', 'message': 'Job ID required'}), 400
    
    job = scraping_jobs.get(job_id)
    if not job:
        return jsonify({'status': 'error', 'message': 'Job not found'}), 404
    
    return jsonify({
        'status': job['status'],
        'progress': job['progress'],
        'result_file': job.get('result_file')
    })

@app.route('/results')
def results():
    job_id = session.get('job_id')
    if not job_id or job_id not in scraping_jobs:
        flash('스크래핑 결과를 찾을 수 없습니다.')
        return redirect(url_for('index'))
    
    job = scraping_jobs[job_id]
    if job['status'] != '완료' or not job['result_file']:
        flash('스크래핑이 아직 완료되지 않았습니다.')
        return redirect(url_for('scraping_status'))
    
    try:
        df = pd.read_excel(job['result_file'])
        channels = df.to_dict('records')
        return render_template('results.html', 
                               channels=channels, 
                               keyword=job['keyword'], 
                               total_channels=len(channels))
    except Exception as e:
        flash(f'결과 파일 읽기 오류: {str(e)}')
        return redirect(url_for('index'))

if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    app.run(debug=True)
