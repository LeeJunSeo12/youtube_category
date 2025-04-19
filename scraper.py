import sys
import time
import random
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import pandas as pd
from collections import OrderedDict

def run_scraper(search_keyword, max_channels, job_id=None, progress_callback=None):
    max_channels = int(max_channels)
    
    # Chrome 옵션 설정
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")

    # WebDriver 초기화
    driver = webdriver.Chrome(options=chrome_options)
    collected_channels = OrderedDict()  # 순서 유지 및 중복 방지
    
    result_file = os.path.join('data', f'youtube_channels_{job_id}.xlsx')

    try:
        # YouTube 검색 페이지 접속
        url = f"https://www.youtube.com/results?search_query={search_keyword}&sp=EgIQAg%253D%253D"
        driver.get(url)
        time.sleep(random.uniform(1.5, 3.0))

        last_height = driver.execute_script("return document.documentElement.scrollHeight")
        scroll_attempt = 0
        batch_size = 1000  # 배치 저장 단위

        while len(collected_channels) < max_channels:
            # 스크롤 다운 및 새 콘텐츠 로딩 대기
            driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
            time.sleep(random.uniform(1.0, 2.5))
            
            # 채널 요소 수집
            channel_links = driver.find_elements(By.XPATH, '//a[contains(@href, "/channel/") or contains(@href, "/@")]')
            
            for link in channel_links:
                try:
                    name = link.text.strip()
                    url = link.get_attribute('href')
                    if name and url not in collected_channels:
                        collected_channels[url] = name
                        if len(collected_channels) >= max_channels:
                            break
                except Exception as e:
                    print(f"Error extracting channel: {str(e)}")
            
            # 진행 상황 콜백
            if progress_callback and job_id:
                progress_callback(job_id, len(collected_channels), max_channels)
            
            # 배치 저장
            if len(collected_channels) % batch_size == 0:
                save_to_excel(collected_channels, result_file)
            
            # 스크롤 종료 조건 검사
            new_height = driver.execute_script("return document.documentElement.scrollHeight")
            if new_height == last_height:
                scroll_attempt += 1
                if scroll_attempt >= 5:
                    print("추가 콘텐츠 로딩 중단. 스크래핑 종료")
                    break
            else:
                scroll_attempt = 0
                last_height = new_height

    except Exception as e:
        print(f"오류 발생: {str(e)}")
        raise
    finally:
        # 최종 저장 및 리소스 정리
        save_to_excel(collected_channels, result_file)
        driver.quit()
        print(f"스크래핑 완료. 결과 파일: {result_file}")
        return result_file

def save_to_excel(channels, filename):
    df = pd.DataFrame({
        '채널명': list(channels.values()),
        '채널URL': list(channels.keys())
    })
    
    # 디렉토리 확인 및 생성
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    # 파일 존재 시 추가 저장
    try:
        existing_df = pd.read_excel(filename)
        combined_df = pd.concat([existing_df, df], ignore_index=True)
        combined_df.drop_duplicates(subset=['채널URL'], keep='first', inplace=True)
        combined_df.to_excel(filename, index=False)
    except FileNotFoundError:
        df.to_excel(filename, index=False)

if __name__ == "__main__":
    # 명령줄 인수 처리
    if len(sys.argv) < 3:
        print("Usage: python scraper.py [검색어] [수집할_채널_수]")
        sys.exit(1)
    
    search_keyword = sys.argv[1]
    max_channels = int(sys.argv[2])
    run_scraper(search_keyword, max_channels)
