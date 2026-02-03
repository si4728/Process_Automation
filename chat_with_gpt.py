import os
from openai import OpenAI

# 환경변수에서 키를 읽는지 확인(출력은 앞 5글자만)
key = os.getenv("OPENAI_API_KEY")
if not key:
    raise RuntimeError("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.")
print("OPENAI_API_KEY startswith:", key[:5])

client = OpenAI()  # 기본적으로 OPENAI_API_KEY를 자동으로 사용

resp = client.responses.create(
    model="gpt-5",
    input="환경변수 테스트입니다. OK 라고만 답해줘."
)
print(resp.output_text)
