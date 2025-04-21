from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import pandas as pd
import threading
import time
from scraper import run_scraper
import uuid
from datetime import timedelta
import hashlib
from flask import send_file
from collections import defaultdict
from threading import Lock

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))
app.config.update(
    UPLOAD_FOLDER='data',
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_SAMESITE='Lax'
)

# CSRF 토큰 생성 함수
def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = hashlib.sha256(os.urandom(24)).hexdigest()
    return session['csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

# 다중 사용자 지원을 위한 구조 변경
scraping_jobs = defaultdict(dict)  # {user_id: {job_id: job_data}}
job_lock = Lock()

def get_user_id():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    return session['user_id']

@app.route('/', methods=['GET', 'POST'])
def index():
    user_id = get_user_id()
    # 기존 작업 정리
    if user_id in scraping_jobs:
        for job_id in list(scraping_jobs[user_id].keys()):
            result_file = os.path.join('data', f'youtube_channels_{job_id}.xlsx')
            if os.path.exists(result_file):
                try:
                    os.remove(result_file)
                except Exception as e:
                    print(f"파일 삭제 오류: {e}")
        del scraping_jobs[user_id]
    session.pop('job_id', None)
    return render_template('index.html')

@app.route('/start_scraping', methods=['POST'])
def start_scraping():
    # CSRF 토큰 검증
    if request.form.get('csrf_token') != session.get('csrf_token'):
        flash('잘못된 요청입니다.')
        return redirect(url_for('index'))

    user_id = get_user_id()
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
    with job_lock:
        scraping_jobs[user_id][job_id] = {
            'status': '진행 중',
            'progress': 0,
            'keyword': keyword,
            'max_channels': max_channels,
            'result_file': None
        }
    
    session['job_id'] = job_id
    session.modified = True
    
    # 스크래핑 스레드 시작
    thread = threading.Thread(
        target=run_scraper_thread,
        args=(user_id, job_id, keyword, max_channels)
    )
    thread.daemon = True
    thread.start()
    
    return redirect(url_for('scraping_status'))

def run_scraper_thread(user_id, job_id, keyword, max_channels):
    try:
        result_file = run_scraper(
            keyword, 
            max_channels, 
            job_id, 
            lambda c, t: progress_callback(user_id, job_id, c, t)
        )
        with job_lock:
            scraping_jobs[user_id][job_id]['status'] = '완료'
            scraping_jobs[user_id][job_id]['result_file'] = result_file
    except Exception as e:
        with job_lock:
            scraping_jobs[user_id][job_id]['status'] = '오류'
            scraping_jobs[user_id][job_id]['error'] = str(e)

def progress_callback(user_id, job_id, current, total):
    with job_lock:
        if user_id in scraping_jobs and job_id in scraping_jobs[user_id]:
            scraping_jobs[user_id][job_id]['progress'] = int((current / total) * 100)

@app.route('/status')
def scraping_status():
    user_id = get_user_id()
    job_id = session.get('job_id')
    
    if not job_id or user_id not in scraping_jobs or job_id not in scraping_jobs[user_id]:
        flash('스크래핑 작업을 찾을 수 없습니다.')
        return redirect(url_for('index'))
    
    job = scraping_jobs[user_id][job_id]
    return render_template('status.html', job=job)

@app.route('/get_status')
def get_status():
    user_id = get_user_id()
    job_id = request.args.get('job_id') or session.get('job_id')
    
    if not job_id or user_id not in scraping_jobs or job_id not in scraping_jobs[user_id]:
        return jsonify({'status': 'error', 'message': 'Job not found'}), 404
    
    job = scraping_jobs[user_id][job_id]
    response_data = {
        'status': job['status'],
        'progress': job['progress']
    }
    
    if job['status'] == '완료':
        response_data['redirect'] = url_for('results')
    
    return jsonify(response_data)

@app.route('/results')
def results():
    user_id = get_user_id()
    job_id = session.get('job_id')
    
    if not job_id or user_id not in scraping_jobs or job_id not in scraping_jobs[user_id]:
        flash('스크래핑 결과를 찾을 수 없습니다.')
        return redirect(url_for('index'))
    
    job = scraping_jobs[user_id][job_id]
    if job['status'] != '완료' or not job['result_file']:
        flash('스크래핑이 아직 완료되지 않았습니다.')
        return redirect(url_for('scraping_status'))
    
    try:
        df = pd.read_excel(job['result_file'])
        channels = df.to_dict('records')
        return render_template('results.html', 
                             channels=channels, 
                             keyword=job['keyword'], 
                             total_channels=len(channels),
                             job_id=job_id)
    except Exception as e:
        flash(f'결과 파일 읽기 오류: {str(e)}')
        return redirect(url_for('index'))
    
@app.route('/download/<job_id>')
def download_excel(job_id):
    user_id = get_user_id()
    if user_id not in scraping_jobs or job_id not in scraping_jobs[user_id]:
        flash('파일을 찾을 수 없습니다.')
        return redirect(url_for('index'))
    
    result_file = os.path.join('data', f'youtube_channels_{job_id}.xlsx')
    return send_file(
        result_file,
        as_attachment=True,
        download_name=f'youtube_channels_{job_id}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    app.run(host='0.0.0.0', port=8080, threaded=True)
