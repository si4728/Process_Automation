from google import genai
import os
import configparser
from pathlib import Path
from docx import Document
import llm_config

# 1. 클라이언트 설정
api_key="AIzaSyCikeCR89pfyLZRjDUzgVMZ88V8ATfVJjc"
if not api_key:
    # 환경변수가 없다면 여기에 직접 입력 (테스트용)
    api_key = "YOUR_ACTUAL_API_KEY_HERE"
    
client = genai.Client(api_key=api_key)

def get_gemini_response(model_name, user_input):
    """Gemini API를 호출하여 응답을 반환합니다."""
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=user_input
        )
        return response.text
    except Exception as e:
        return f"API 호출 중 오류 발생: {e}"    

def save_llm_docx(subject: str, text: str, output_path: str):
    
    doc = Document()
    doc.add_heading(f"{subject} LLM 분석결과", level=1)
    doc.add_paragraph("")
    doc.add_paragraph("")

    # 줄 단위로 문단 구성
    for line in text.splitlines():
        if line.strip():
            doc.add_paragraph(line)
        else:
            doc.add_paragraph("")  # 빈 줄 유지

    doc.save(output_path)

def main():
    # 1. 설정 파일 읽기
    config = configparser.ConfigParser()
    #config_file = "llm_config.ini"

    config_file = llm_config.get_last_gemini_settings_ini()
    print("llm config file:")
    
    if not os.path.exists(config_file):
        print(f"오류: 설정 파일({config_file})이 존재하지 않습니다.")
        return

    config.read(config_file, encoding='utf-8')
    
    # 세션 이름은 [GEMINI_SETTINGS] 기준
    section = 'GEMINI_SETTINGS'
    model_name = config.get(section, 'model', fallback='gemini-2.5-flash')
    target_file = config.get(section, 'file_path')
    user_prompt = config.get(section, 'prompt')
    chunk_chars = config.getint(section, 'chunk_chars', fallback=64000)
    output_file_path = config.get(section, 'output_file_path')
   
    # 2. 대상 파일 읽기
    file_path = Path(target_file)
    if not file_path.exists():
        print(f"오류: 분석할 파일을 찾을 수 없습니다: {target_file}")
        return

    try:
        # 파일 내용을 텍스트로 변환
        file_content = file_path.read_text(encoding='utf-8', errors='ignore')
        if len(file_content) > chunk_chars:
            file_content = file_content[:chunk_chars]
            print(f"주의: 파일이 너무 길어 상위 {chunk_chars}자만 읽었습니다.")
    except Exception as e:
        print(f"파일 읽기 오류: {e}")
        return

    # 3. 프롬프트 구성
    full_input = f"다음 내용을 바탕으로 요청사항을 수행해줘.\n\n[파일 내용]\n{file_content}\n\n[요청사항]\n{user_prompt}"

    # 4. Gemini API 호출
    
    print(f"[{model_name}] 모델을 사용하여 작업을 시작합니다...")
    result = get_gemini_response(model_name, full_input)

    # 5. 결과 출력
    print("\n" + "="*50)
    print("[Gemini 분석 결과]")
    print("="*50)
    print(result)
    
    save_llm_docx(file_path, result, output_file_path)
    print(f"saved: {output_file_path}")

if __name__ == "__main__":
    main()