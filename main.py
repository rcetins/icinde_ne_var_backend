from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
import os
import json
import re

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


def normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_ocr_text_weak(text: str) -> bool:
    clean = normalize_text(text)

    if len(clean) < 25:
        return True

    letters = re.findall(r"[a-zA-ZğüşöçıİĞÜŞÖÇ]", clean)
    if len(letters) < 15:
        return True

    # Çok fazla anlamsız karakter varsa OCR zayıf kabul edilir.
    non_text_chars = re.findall(r"[^a-zA-ZğüşöçıİĞÜŞÖÇ0-9\s,.;:%()/+\-]", clean)
    if len(non_text_chars) > max(10, len(clean) * 0.25):
        return True

    return False


def extract_relevant_content(text: str) -> str:
    clean = normalize_text(text)
    lower = clean.lower()

    keywords = [
        "içindekiler",
        "icindekiler",
        "ingredients",
        "ingredient",
        "composition",
        "inci",
        "contents",
        "bileşenler",
        "bilesenler",
    ]

    for keyword in keywords:
        idx = lower.find(keyword)
        if idx != -1:
            extracted = clean[idx:]
            return extracted[:1200]

    return clean[:1200]


def local_content_analysis(text: str):
    lower = text.lower()

    high_risk_terms = [
        "aspartam", "acesulfam", "sodyum nitrit", "nitrit", "e250", "e251", "e252",
        "monosodyum glutamat", "msg", "e621", "glikoz şurubu", "glikoz surubu",
        "fruktoz şurubu", "fruktoz surubu", "mısır şurubu", "misir surubu",
        "hidrojene", "trans yağ", "trans yag", "titanyum dioksit", "e171",
        "formaldehit", "triclosan", "hydroquinone", "hidrokinon",
    ]

    attention_terms = [
        "şeker", "seker", "palm", "aroma", "renklendirici", "koruyucu",
        "emülgatör", "emulgator", "tatlandırıcı", "tatlandirici",
        "gluten", "soya", "alkol", "parfüm", "parfum", "fragrance",
        "phenoxyethanol", "phenoxyethanol", "sls", "sles", "paraben",
        "silikon", "silicone", "mineral oil", "paraffinum liquidum",
    ]

    high_found = [term for term in high_risk_terms if term in lower]
    attention_found = [term for term in attention_terms if term in lower]

    if high_found:
        return {
            "title": "🔴 Yüksek Dikkat",
            "message": (
                "Dikkat gerektiren içerikler tespit edildi: "
                + ", ".join(high_found[:4])
                + ". Bu sonuç bilgilendirme amaçlıdır; nihai tercih kullanıcıya aittir."
            ),
            "risk": "high"
        }

    if len(attention_found) >= 2:
        return {
            "title": "🟡 Dikkat Gerektirir",
            "message": (
                "Bazı içerikler hassas kişiler için dikkat gerektirebilir: "
                + ", ".join(attention_found[:5])
                + ". Sık kullanım/tüketimde etiketi dikkatli değerlendirin."
            ),
            "risk": "medium"
        }

    if len(attention_found) == 1:
        return {
            "title": "🟡 Düşük-Orta Dikkat",
            "message": (
                f"Okunan içerikte dikkat edilebilecek bir madde görüldü: {attention_found[0]}. "
                "Genel değerlendirme için metnin tamamının net okunduğundan emin olun."
            ),
            "risk": "medium"
        }

    return {
        "title": "🟡 İnceleme Gerekli",
        "message": (
            "Okunan metinde bilinen yüksek riskli madde yakalanmadı; ancak içerik listesi sınırlı okunmuş olabilir. "
            "Daha net sonuç için içindekiler alanını sarı çerçeveye hizalayıp tekrar deneyin."
        ),
        "risk": "medium"
    }


@app.post("/analyze-content")
async def analyze_content(data: ContentRequest):
    raw_text = normalize_text(data.text)
    content_text = extract_relevant_content(raw_text)

    if is_ocr_text_weak(content_text):
        return {
            "title": "🟡 Yazı Net Okunamadı",
            "message": "İçindekiler alanı yeterince net okunamadı. Ürünü sabitleyip sarı çerçeveye yaklaştırarak tekrar deneyin.",
            "risk": "medium",
            "read_text": content_text
        }

    # Önce hızlı yerel analiz yapılır. AI hata verirse bu döner.
    fallback = local_content_analysis(content_text)

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
Sen 'İçinde Ne Var?' uygulaması için gıda ve kozmetik içerik analiz motorusun.

Görevin:
- Kullanıcının OCR ile okuttuğu ürün içeriğini değerlendir.
- Gıda ve kozmetik ürünlerini birlikte anlayabil.
- Dünya genelinde kabul gören sağlık otoritelerinin yaklaşımını dikkate al:
  WHO/FAO JECFA katkı maddesi değerlendirmeleri, Codex gıda katkı standartları,
  IARC kanserojen sınıflandırmaları, EFSA/FDA gibi kurumların güvenlik yaklaşımı.
- Kesin tıbbi hüküm verme.
- "Al" veya "alma" deme.
- Kararı kullanıcıya bırak.
- Metin zayıf/eksikse ASLA düşük risk deme; "Yazı net okunamadı" veya "Dikkat" dön.
- Cevap kısa, net, kullanıcıya faydalı ve Türkçe olsun.

Risk mantığı:
high = tartışmalı, hassasiyet oluşturabilecek veya sık tüketim/kullanımda dikkat gerektiren güçlü içerik varsa.
medium = şeker, palm, aroma, koruyucu, renklendirici, parfüm, alkol, SLS/SLES/paraben vb. dikkat gerektiren içerikler varsa veya metin eksikse.
low = sadece içerik listesi yeterince net ve riskli/dikkat gerektiren madde yoksa.

JSON dışında hiçbir şey yazma.
JSON formatı:
{
  "title": "🔴/🟡/🟢 kısa başlık",
  "message": "2-4 kısa cümlelik açıklama. Tespit edilen 1-4 önemli maddeyi belirt. Nihai karar kullanıcıya aittir.",
  "risk": "high | medium | low"
}
"""
                },
                {
                    "role": "user",
                    "content": f"OCR ile okunan içerik metni:\n{content_text}"
                }
            ],
            temperature=0.2,
            max_tokens=300
        )

        result_text = response.choices[0].message.content.strip()

        try:
            result = json.loads(result_text)
        except Exception:
            return {
                **fallback,
                "read_text": content_text
            }

        title = result.get("title") or fallback["title"]
        message = result.get("message") or fallback["message"]
        risk = result.get("risk") or fallback["risk"]

        if risk not in ["high", "medium", "low"]:
            risk = "medium"

        return {
            "title": title,
            "message": message,
            "risk": risk,
            "read_text": content_text
        }

    except Exception as e:
        return {
            **fallback,
            "read_text": content_text,
            "debug": str(e)
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
Sen profesyonel bir besin analizi asistanısın.

Kullanıcının gönderdiği yemek/öğün görüntüsünü analiz et.
Kısa, net ve tahmini değer ver.
Kesin laboratuvar sonucu gibi konuşma.
Porsiyon belirsizse "tahmini" olduğunu belirt.

Şu formatı koru:

Enerji: %10
Kalori: 550 kcal
Protein: 20g
Karbonhidrat: 40g
Yağ: 18g
Kısa yorum: ...
"""
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Bu öğünün tahmini besin değerlerini analiz et."
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
            max_tokens=250,
            temperature=0.2
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
            "message": f"Besin analizi şu anda tamamlanamadı. Hata: {str(e)}",
            "risk": "medium"
        }
