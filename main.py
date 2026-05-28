from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
import os
import json
import re

load_dotenv()

app = FastAPI()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class ContentRequest(BaseModel):
    text: str
    language: str = "tr"


class NutritionRequest(BaseModel):
    image: str
    language: str = "tr"


@app.get("/")
def root():
    return {"message": "İçinde Ne Var Backend Çalışıyor"}


def normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_relevant_content(text: str) -> str:
    clean = normalize_text(text)
    lower = clean.lower()

    start_keywords = [
        "içindekiler", "icindekiler", "ingredients", "ingredient",
        "composition", "contents", "inci", "bileşenler", "bilesenler",
        "formula", "formül", "formul"
    ]

    start_index = -1
    for keyword in start_keywords:
        idx = lower.find(keyword)
        if idx != -1 and (start_index == -1 or idx < start_index):
            start_index = idx

    extracted = clean[start_index:] if start_index != -1 else clean
    lower_extracted = extracted.lower()

    stop_keywords = [
        "üretici", "uretici", "ithalatçı", "ithalatci", "tavsiye edilen",
        "son tüketim", "son tuketim", "saklama koşulları", "saklama kosullari",
        "menşei", "mensei", "net miktar", "barkod", "barcode",
        "made in", "distributed by", "manufacturer", "www.", "tel:",
        "customer", "art no", "batch", "lot", "paşabahçe"
    ]

    stop_index = -1
    for keyword in stop_keywords:
        idx = lower_extracted.find(keyword)
        if idx > 40 and (stop_index == -1 or idx < stop_index):
            stop_index = idx

    if stop_index != -1:
        extracted = extracted[:stop_index]

    return extracted[:1400].strip()


def ocr_quality(text: str) -> dict:
    clean = normalize_text(text)
    lower = clean.lower()

    letters = re.findall(r"[a-zA-ZğüşöçıİĞÜŞÖÇ]", clean)
    comma_like = clean.count(",") + clean.count(";")
    has_content_keyword = any(
        k in lower for k in [
            "içindekiler", "icindekiler", "ingredients", "composition",
            "contents", "inci", "bileşenler", "bilesenler"
        ]
    )

    if len(clean) < 30 or len(letters) < 20:
        return {
            "weak": True,
            "can_be_low": False,
            "reason": "Metin çok kısa veya net değil."
        }

    weird_chars = re.findall(r"[^a-zA-ZğüşöçıİĞÜŞÖÇ0-9\s,.;:%()/+\-]", clean)
    if len(weird_chars) > max(12, len(clean) * 0.22):
        return {
            "weak": True,
            "can_be_low": False,
            "reason": "OCR metninde fazla anlamsız karakter var."
        }

    # Düşük risk diyebilmek için metin gerçekten içerik listesine benzemeli.
    can_be_low = has_content_keyword or comma_like >= 3 or len(clean) >= 120

    return {
        "weak": False,
        "can_be_low": can_be_low,
        "reason": "Metin okunabilir."
    }


HIGH_TERMS = [
    # Gıda katkıları / tartışmalı içerikler
    "aspartam", "aspartame", "acesulfam", "acesulfame", "acesulfame k",
    "sodyum nitrit", "sodium nitrite", "nitrit", "nitrite",
    "e250", "e251", "e252", "monosodyum glutamat", "monosodium glutamate",
    "msg", "e621", "glikoz şurubu", "glikoz surubu", "glucose syrup",
    "fruktoz şurubu", "fruktoz surubu", "fructose syrup",
    "mısır şurubu", "misir surubu", "corn syrup", "high fructose",
    "hidrojene", "hydrogenated", "trans yağ", "trans yag", "trans fat",
    "titanyum dioksit", "titanium dioxide", "e171",
    # Kozmetik / hassasiyet ve tartışmalı içerikler
    "formaldehit", "formaldehyde", "triclosan", "hydroquinone",
    "hidrokinon", "methylisothiazolinone", "methylchloroisothiazolinone",
    "bha", "bht", "retinyl palmitate"
]

MEDIUM_TERMS = [
    # Gıda
    "şeker", "seker", "sugar", "palm", "aroma", "flavour", "flavor",
    "renklendirici", "colorant", "koruyucu", "preservative",
    "emülgatör", "emulgator", "emulsifier", "tatlandırıcı", "tatlandirici",
    "sweetener", "gluten", "soya", "soy", "nişasta", "nisasta", "starch",
    # Kozmetik
    "alkol", "alcohol", "parfüm", "parfum", "fragrance", "sls", "sles",
    "sodium lauryl sulfate", "sodium laureth sulfate", "paraben",
    "phenoxyethanol", "mineral oil", "paraffinum liquidum", "silicone",
    "dimethicone", "petrolatum", "peg-", "ci "
]


def local_content_analysis(text: str, quality: dict) -> dict:
    lower = text.lower()

    high_found = [term for term in HIGH_TERMS if term in lower]
    medium_found = [term for term in MEDIUM_TERMS if term in lower]

    if quality["weak"]:
        return {
            "title": "🟡 Yazı Net Okunamadı",
            "message": (
                "İçerik listesi yeterince net okunamadı. Daha doğru sonuç için ürünü sabitleyip "
                "içindekiler alanını sarı çerçeveye yaklaştırın."
            ),
            "risk": "medium",
            "read_text": text
        }

    if high_found:
        return {
            "title": "🔴 Yüksek Dikkat",
            "message": (
                "Dikkat gerektiren içerikler tespit edildi: "
                + ", ".join(high_found[:5])
                + ". Bu değerlendirme bilgilendirme amaçlıdır; nihai karar kullanıcıya aittir."
            ),
            "risk": "high",
            "read_text": text
        }

    if len(medium_found) >= 1:
        return {
            "title": "🟡 Orta Risk",
            "message": (
                "Dikkat edilmesi gereken içerikler görüldü: "
                + ", ".join(medium_found[:6])
                + ". Hassasiyet, sık tüketim/kullanım ve kişisel durumlar sonucu değiştirebilir."
            ),
            "risk": "medium",
            "read_text": text
        }

    if not quality["can_be_low"]:
        return {
            "title": "🟡 Orta Risk",
            "message": (
                "Metin okunabilir ama içerik listesi tam yakalanmamış olabilir. Net karar için "
                "İçindekiler/Ingredients alanını daha doğrudan okutun."
            ),
            "risk": "medium",
            "read_text": text
        }

    return {
        "title": "🟢 Düşük Risk",
        "message": (
            "Okunan içerik listesinde belirgin yüksek riskli veya dikkat gerektiren madde yakalanmadı. "
            "Bu sonuç yalnızca okunan metne göre bilgilendirme amaçlıdır."
        ),
        "risk": "low",
        "read_text": text
    }


def risk_rank(risk: str) -> int:
    risk = (risk or "").lower()
    if risk == "high":
        return 3
    if risk == "medium":
        return 2
    if risk == "low":
        return 1
    return 2


def normalize_risk(risk: str) -> str:
    risk = (risk or "").lower().strip()
    if risk in ["high", "medium", "low"]:
        return risk
    return "medium"


@app.post("/analyze-content")
async def analyze_content(data: ContentRequest):
    raw_text = normalize_text(data.text)
    content_text = extract_relevant_content(raw_text)
    quality = ocr_quality(content_text)

    fallback = local_content_analysis(content_text, quality)

    # Zayıf OCR varsa AI'ya bile sormadan orta risk / net okunamadı döndür.
    if quality["weak"]:
        return fallback

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
Sen 'İçinde Ne Var?' uygulamasının gıda ve kozmetik içerik analiz motorusun.

Temel kurallar:
- Kullanıcıya "al" veya "alma" deme.
- Kesin tıbbi hüküm verme.
- Nihai karar kullanıcıya aittir.
- Emin değilsen ASLA düşük risk verme; medium dön.
- OCR metni eksik veya içerik listesi tam değilse medium dön.
- Düşük risk sadece içerik listesi yeterince net ve dikkat gerektiren madde görünmüyorsa verilir.
- Cevap Türkçe, kısa ve net olsun.

Referans yaklaşımı:
- Gıda için WHO/FAO JECFA, Codex GSFA, EFSA/FDA güvenlik yaklaşımını dikkate al.
- Kanserojenlik tehlikesi için IARC sınıflandırma mantığını dikkate al.
- Kozmetik için paraben, SLS/SLES, alkol, fragrance/parfum, phenoxyethanol, formaldehyde salıcılar,
  triclosan, hydroquinone, methylisothiazolinone gibi hassasiyet/tartışmalı içerikleri önemse.

Risk:
high = nitrit/nitrat türevleri, aspartam/acesulfame, MSG/E621, trans/hidrojene yağ, titanium dioxide/E171,
       formaldehyde, triclosan, hydroquinone, methylisothiazolinone gibi güçlü dikkat gerektiren içerikler varsa.
medium = şeker, palm, aroma, koruyucu, renklendirici, emülgatör, tatlandırıcı, SLS/SLES, paraben,
         fragrance/parfum, alkol, mineral oil/paraffinum liquidum, phenoxyethanol gibi dikkat içerikleri varsa.
low = sadece metin net ve belirgin dikkat/yüksek risk maddesi yoksa.

JSON dışında hiçbir şey yazma.
JSON:
{
  "title": "🔴/🟡/🟢 kısa başlık",
  "message": "2-4 kısa cümle. Yakalanan önemli maddeleri belirt. Nihai karar kullanıcıya aittir.",
  "risk": "high | medium | low"
}
"""
                },
                {
                    "role": "user",
                    "content": f"OCR ile okunan ürün içeriği:\n{content_text}"
                }
            ],
            temperature=0,
            max_tokens=350
        )

        result_text = response.choices[0].message.content.strip()

        try:
            ai_result = json.loads(result_text)
        except Exception:
            return fallback

        ai_risk = normalize_risk(ai_result.get("risk"))
        fallback_risk = fallback["risk"]

        # Güvenlik kuralı: AI, yerel motorun riskini düşüremez.
        # Örn local medium iken AI low diyorsa medium kalır.
        if risk_rank(ai_risk) < risk_rank(fallback_risk):
            final_risk = fallback_risk
        else:
            final_risk = ai_risk

        # Ayrıca düşük risk için OCR kalitesi ve içerik benzerliği şart.
        if final_risk == "low" and not quality["can_be_low"]:
            final_risk = "medium"

        if final_risk == fallback_risk and fallback_risk != ai_risk:
            return fallback

        return {
            "title": ai_result.get("title") or fallback["title"],
            "message": ai_result.get("message") or fallback["message"],
            "risk": final_risk,
            "read_text": content_text
        }

    except Exception as e:
        return {
            **fallback,
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

Görüntüdeki yemeği/öğünü tahmini analiz et.
Kesin laboratuvar sonucu gibi konuşma.
Porsiyon belirsizse tahmini olduğunu belirt.
Kısa, net, kullanıcı dostu cevap ver.

Format:
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
                        {"type": "text", "text": "Bu öğünün tahmini besin değerlerini analiz et."},
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
