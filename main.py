from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
import os
import base64

load_dotenv()

app = FastAPI()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


class ContentRequest(BaseModel):
    text: str
    language: str = "tr"


class NutritionRequest(BaseModel):
    image: str
    language: str = "tr"


@app.get("/")
def root():
    return {
        "message": "İçinde Ne Var Backend Çalışıyor"
    }


@app.post("/analyze-content")
async def analyze_content(data: ContentRequest):

    text = data.text.lower()

    red_words = [
        "aspartam",
        "glikoz şurubu",
        "fruktoz şurubu",
        "nitrit",
        "e621",
        "msg",
        "paraben",
        "sls",
        "sles",
    ]

    yellow_words = [
        "şeker",
        "palm",
        "aroma",
        "koruyucu",
        "renklendirici",
        "alkol",
        "parfüm",
    ]

    red_count = sum(word in text for word in red_words)
    yellow_count = sum(word in text for word in yellow_words)

    if red_count > 0:
        return {
            "title": "🔴 Yüksek Risk",
            "message": "Tartışmalı içerikler tespit edildi.",
            "risk": "high"
        }

    if yellow_count >= 2:
        return {
            "title": "🟡 Orta Risk",
            "message": "Dikkat edilmesi gereken içerikler mevcut.",
            "risk": "medium"
        }

    return {
        "title": "🟢 Düşük Risk",
        "message": "Yüksek riskli içerik bulunamadı.",
        "risk": "low"
    }


@app.post("/analyze-nutrition")
async def analyze_nutrition(data: NutritionRequest):

    try:

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
                    Sen profesyonel bir besin analiz uzmanısın.

                    Kullanıcının gönderdiği yemek görüntüsünü analiz et.

                    Kısa ve net cevap ver.

                    Şu formatta cevap ver:

                    Enerji: %10
                    Kalori: 550 kcal
                    Protein: 20g
                    Karbonhidrat: 40g
                    Yağ: 18g
                    """
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Bu tabağın besin değerlerini analiz et."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{data.image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=200
        )

        result = response.choices[0].message.content

        return {
            "title": "🟢 Besin Analizi",
            "message": result,
            "risk": "low"
        }

    except Exception as e:

        return {
            "title": "🟡 Besin Analizi",
            "message": f"Hata oluştu: {str(e)}",
            "risk": "medium"
        }