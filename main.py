from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
import os
import json
import re
import urllib.parse
import urllib.request

load_dotenv()

app = FastAPI()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class ContentRequest(BaseModel):
    text: str = ""
    image: str | None = None
    language: str = "tr"


class NutritionRequest(BaseModel):
    image: str
    language: str = "tr"



class PriceRequest(BaseModel):
    image: str | None = None
    text: str = ""
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
        "menşei", "mensei", "net miktar", "barkod", "barcode", "made in",
        "distributed by", "manufacturer", "www.", "tel:", "customer",
        "art no", "batch", "lot"
    ]

    stop_index = -1
    for keyword in stop_keywords:
        idx = lower_extracted.find(keyword)
        if idx > 40 and (stop_index == -1 or idx < stop_index):
            stop_index = idx

    if stop_index != -1:
        extracted = extracted[:stop_index]

    return extracted[:1800].strip()


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

    can_be_low = has_content_keyword or comma_like >= 3 or len(clean) >= 120

    return {
        "weak": False,
        "can_be_low": can_be_low,
        "reason": "Metin okunabilir."
    }


# Uygulamanın hızlı/yedek karar motoru.
# Amaç: AI hata verse bile her şeyi yeşile düşürmemek.
TERM_INFO = {
    "aspartam": {
        "risk": "high",
        "name": "Aspartam",
        "purpose": "Şekersiz veya düşük kalorili ürünlerde tatlandırıcı olarak kullanılır.",
        "effect": "Hassas kişilerde dikkat gerektirebilir. Fenilketonüri hastaları için uygun değildir; sık tüketimde toplam tatlandırıcı alımı değerlendirilmelidir."
    },
    "acesulfam": {
        "risk": "high",
        "name": "Acesulfam K",
        "purpose": "Kalorisiz tatlandırıcı olarak kullanılır.",
        "effect": "Tek başına kesin zarar hükmü verilemez; fakat sık tüketilen diyet ürünlerde toplam yapay tatlandırıcı yükü açısından dikkat gerektirir."
    },
    "sodyum nitrit": {
        "risk": "high",
        "name": "Sodyum nitrit / Nitrit",
        "purpose": "İşlenmiş et ürünlerinde renk koruma ve mikrobiyal dayanıklılık için kullanılır.",
        "effect": "İşlenmiş et ürünleriyle birlikte değerlendirildiğinde sık tüketimde dikkat edilmesi gereken katkılardandır."
    },
    "nitrit": {
        "risk": "high",
        "name": "Nitrit",
        "purpose": "Özellikle işlenmiş etlerde koruyucu ve renk sabitleyici olarak kullanılır.",
        "effect": "Sık tüketimde dikkat gerektirir; ürün türü ve tüketim sıklığı önemlidir."
    },
    "e250": {
        "risk": "high",
        "name": "E250 - Sodyum nitrit",
        "purpose": "İşlenmiş etlerde koruyucu ve renk sabitleyici olarak kullanılır.",
        "effect": "İşlenmiş et tüketimi bağlamında dikkat edilmesi gereken katkılardandır."
    },
    "e621": {
        "risk": "high",
        "name": "E621 / MSG",
        "purpose": "Lezzet artırıcı olarak kullanılır.",
        "effect": "Bazı hassas kişilerde baş ağrısı, rahatsızlık veya hassasiyet bildirimleri olabilir; sık tüketimde dikkat önerilir."
    },
    "monosodyum glutamat": {
        "risk": "high",
        "name": "Monosodyum glutamat",
        "purpose": "Lezzet artırıcı olarak kullanılır.",
        "effect": "Hassas kişilerde rahatsızlık yapabilir; özellikle yoğun işlenmiş gıdalarda dikkat gerektirir."
    },
    "glikoz şurubu": {
        "risk": "high",
        "name": "Glikoz şurubu",
        "purpose": "Tatlandırma, kıvam ve raf ömrü için kullanılır.",
        "effect": "Şeker yükünü artırabilir; sık tüketimde kan şekeri ve kalori alımı açısından dikkat gerektirir."
    },
    "fruktoz şurubu": {
        "risk": "high",
        "name": "Fruktoz şurubu",
        "purpose": "Tatlandırıcı şurup olarak kullanılır.",
        "effect": "Sık tüketimde yüksek şeker alımına katkı sağlayabilir; özellikle içecek ve atıştırmalıklarda dikkat gerektirir."
    },
    "mısır şurubu": {
        "risk": "high",
        "name": "Mısır şurubu",
        "purpose": "Tatlandırma ve kıvam için kullanılır.",
        "effect": "Şeker ve kalori yükünü artırabilir; sık tüketimde dikkat gerektirir."
    },
    "hidrojene": {
        "risk": "high",
        "name": "Hidrojene yağ",
        "purpose": "Ürünün kıvamını ve raf dayanımını artırmak için kullanılır.",
        "effect": "Doymuş/trans yağ içeriği açısından dikkat gerektirebilir; sık tüketimde kalp-damar sağlığı bakımından değerlendirilmelidir."
    },
    "trans yağ": {
        "risk": "high",
        "name": "Trans yağ",
        "purpose": "Bazı işlenmiş yağ yapılarında bulunabilir.",
        "effect": "Sağlık açısından en çok dikkat edilmesi gereken yağ türlerinden biridir; mümkünse düşük tutulması önerilir."
    },
    "titanyum dioksit": {
        "risk": "high",
        "name": "Titanyum dioksit",
        "purpose": "Beyazlatıcı/renk düzenleyici olarak kullanılmıştır.",
        "effect": "Gıda kullanımında bazı bölgelerde tartışmalı kabul edilir; içerikte görülürse dikkat gerektirir."
    },
    "e171": {
        "risk": "high",
        "name": "E171 - Titanyum dioksit",
        "purpose": "Beyazlatıcı/renk düzenleyici katkı olarak kullanılır.",
        "effect": "Gıda kullanımındaki güvenlik tartışmaları nedeniyle dikkat gerektirir."
    },
    "formaldehit": {
        "risk": "high",
        "name": "Formaldehit / formaldehit salıcılar",
        "purpose": "Bazı ürünlerde koruyucu sistemlerle ilişkilidir.",
        "effect": "Cilt hassasiyeti ve alerjik reaksiyon riski açısından dikkat gerektirir."
    },
    "triclosan": {
        "risk": "high",
        "name": "Triclosan",
        "purpose": "Antibakteriyel etki için kullanılmıştır.",
        "effect": "Güvenlik ve çevresel etkiler açısından tartışmalı içeriklerdendir; kozmetikte dikkat gerektirir."
    },
    "hydroquinone": {
        "risk": "high",
        "name": "Hydroquinone / Hidrokinon",
        "purpose": "Cilt tonu açıcı ürünlerle ilişkilidir.",
        "effect": "Ciltte tahriş ve hassasiyet riski nedeniyle uzman kontrolü gerektirebilecek güçlü içeriklerdendir."
    },
    "methylisothiazolinone": {
        "risk": "high",
        "name": "Methylisothiazolinone",
        "purpose": "Kozmetiklerde koruyucu olarak kullanılır.",
        "effect": "Alerjik temas dermatiti ve cilt hassasiyeti açısından dikkat gerektiren koruyuculardandır."
    },
    "şeker": {
        "risk": "medium",
        "name": "Şeker",
        "purpose": "Tat vermek ve ürünün lezzet profilini artırmak için kullanılır.",
        "effect": "Sık tüketimde kalori ve kan şekeri yükünü artırabilir."
    },
    "sugar": {
        "risk": "medium",
        "name": "Sugar / Şeker",
        "purpose": "Tatlandırıcı olarak kullanılır.",
        "effect": "Sık tüketimde toplam şeker alımını artırabilir."
    },
    "palm": {
        "risk": "medium",
        "name": "Palm yağı",
        "purpose": "Kıvam, yapı ve raf dayanımı için kullanılır.",
        "effect": "Doymuş yağ alımına katkı sağlayabilir; sık tüketimde dikkat önerilir."
    },
    "aroma": {
        "risk": "medium",
        "name": "Aroma",
        "purpose": "Ürüne belirli tat veya koku profili kazandırmak için kullanılır.",
        "effect": "Genelde düşük miktarda kullanılır; ancak yoğun işlenmiş ürünlerde içerik kalitesini değerlendirmek için dikkat edilebilir."
    },
    "renklendirici": {
        "risk": "medium",
        "name": "Renklendirici",
        "purpose": "Ürüne istenen rengi vermek veya rengi standartlaştırmak için kullanılır.",
        "effect": "Bazı hassas kişilerde alerji/hassasiyet oluşturabilir; özellikle çocukların sık tükettiği ürünlerde dikkat önerilir."
    },
    "colorant": {
        "risk": "medium",
        "name": "Colorant / Renklendirici",
        "purpose": "Ürün rengini vermek veya güçlendirmek için kullanılır.",
        "effect": "Hassas kişilerde reaksiyon oluşturabilir; sık kullanım/tüketimde dikkat edilebilir."
    },
    "koruyucu": {
        "risk": "medium",
        "name": "Koruyucu",
        "purpose": "Ürünün bozulmasını geciktirmek ve raf ömrünü uzatmak için kullanılır.",
        "effect": "Her koruyucu zararlı değildir; fakat bazı türleri hassas bünyelerde reaksiyon oluşturabilir."
    },
    "preservative": {
        "risk": "medium",
        "name": "Preservative / Koruyucu",
        "purpose": "Mikrobiyal bozulmayı azaltmak ve raf ömrünü uzatmak için kullanılır.",
        "effect": "Hassas cilt veya hassas bünyelerde dikkat gerektirebilir."
    },
    "emülgatör": {
        "risk": "medium",
        "name": "Emülgatör",
        "purpose": "Yağ ve su gibi karışması zor bileşenleri bir arada tutmak için kullanılır.",
        "effect": "Genelde teknolojik katkıdır; yoğun işlenmiş ürünlerde sık tüketim açısından dikkat edilebilir."
    },
    "tatlandırıcı": {
        "risk": "medium",
        "name": "Tatlandırıcı",
        "purpose": "Şeker yerine veya şekerle birlikte tat vermek için kullanılır.",
        "effect": "Türüne ve kullanım sıklığına göre dikkat gerektirebilir."
    },
    "sls": {
        "risk": "medium",
        "name": "SLS",
        "purpose": "Temizleyici ve köpürtücü olarak kullanılır.",
        "effect": "Hassas ciltlerde kuruluk, tahriş veya hassasiyet yapabilir."
    },
    "sles": {
        "risk": "medium",
        "name": "SLES",
        "purpose": "Temizleyici ve köpük artırıcı olarak kullanılır.",
        "effect": "SLS'e göre daha yumuşak kabul edilse de hassas ciltlerde kuruluk ve tahriş yapabilir."
    },
    "paraben": {
        "risk": "medium",
        "name": "Paraben",
        "purpose": "Kozmetiklerde koruyucu olarak kullanılır.",
        "effect": "Bazı tüketicilerde hassasiyet ve endokrin etkiler konusundaki tartışmalar nedeniyle dikkatle değerlendirilir."
    },
    "fragrance": {
        "risk": "medium",
        "name": "Fragrance / Parfüm",
        "purpose": "Ürüne koku vermek için kullanılır.",
        "effect": "Alerjiye yatkın veya hassas ciltlerde reaksiyon oluşturabilir."
    },
    "parfüm": {
        "risk": "medium",
        "name": "Parfüm",
        "purpose": "Ürüne koku vermek için kullanılır.",
        "effect": "Hassas ciltlerde alerji veya tahriş oluşturabilir."
    },
    "alkol": {
        "risk": "medium",
        "name": "Alkol",
        "purpose": "Çözücü, kurutucu veya taşıyıcı bileşen olarak kullanılabilir.",
        "effect": "Hassas veya kuru ciltlerde kuruluk ve tahriş yapabilir."
    },
    "phenoxyethanol": {
        "risk": "medium",
        "name": "Phenoxyethanol",
        "purpose": "Kozmetiklerde koruyucu olarak kullanılır.",
        "effect": "Belirli sınırlar içinde kullanılır; hassas ciltlerde dikkat gerektirebilir."
    },
    "paraffinum liquidum": {
        "risk": "medium",
        "name": "Paraffinum Liquidum / Mineral yağ",
        "purpose": "Nem tutucu ve yumuşatıcı etki için kullanılır.",
        "effect": "Genelde bariyer etkisi sağlar; akneye yatkın veya hassas ciltlerde ürün tipine göre dikkat edilebilir."
    },
    "mineral oil": {
        "risk": "medium",
        "name": "Mineral oil",
        "purpose": "Nem tutucu/yumuşatıcı olarak kullanılır.",
        "effect": "Cilt üzerinde bariyer oluşturur; bazı cilt tiplerinde ağır gelebilir."
    },
    "dimethicone": {
        "risk": "medium",
        "name": "Dimethicone",
        "purpose": "Ciltte pürüzsüz his ve koruyucu film etkisi oluşturmak için kullanılır.",
        "effect": "Genelde iyi tolere edilir; ancak bazı kullanıcılar silikon içerikleri tercih etmeyebilir."
    },
}


def find_terms(text: str) -> list[dict]:
    lower = text.lower()
    found = []
    seen_names = set()

    # Uzun terimleri önce yakalamak için sıralama.
    for key in sorted(TERM_INFO.keys(), key=len, reverse=True):
        if key in lower:
            item = TERM_INFO[key]
            if item["name"] not in seen_names:
                found.append(item)
                seen_names.add(item["name"])

    return found


def risk_rank(risk: str) -> int:
    risk = (risk or "").lower()
    if risk == "high":
        return 3
    if risk == "medium":
        return 2
    if risk == "low":
        return 1
    return 0


def normalize_risk(risk: str) -> str:
    risk = (risk or "").lower().strip()
    if risk in ["high", "medium", "low", "unknown"]:
        return risk
    return "medium"


def risk_title(risk: str) -> str:
    if risk == "high":
        return "🔴 Yüksek Dikkat"
    if risk == "low":
        return "🟢 Düşük Risk"
    return "🟡 Dikkat Gerektirir"


def local_content_analysis(text: str, quality: dict) -> dict:
    found = find_terms(text)

    if quality["weak"]:
        return {
            "title": "⚠️ İçerik Net Okunamadı",
            "message": (
                "İçerik listesi yeterince net okunamadı. Ürünü sabitleyip içindekiler alanını "
                "daha yakından okutun. Net okunmadan düşük risk sonucu verilmez."
            ),
            "risk": "unknown",
            "read_text": text,
            "detected_items": []
        }

    if found:
        highest = max([item["risk"] for item in found], key=risk_rank)
        shown = found[:5]

        details = []
        for item in shown:
            details.append(
                f"{item['name']}: {item['purpose']} Sağlık açısından: {item['effect']}"
            )

        if highest == "high":
            general = (
                "Genel değerlendirme: Üründe güçlü dikkat gerektiren içerik bulundu. "
                "Bu ürün için kullanım/tüketim sıklığı ve kişisel hassasiyet önemlidir."
            )
        else:
            general = (
                "Genel değerlendirme: Üründe dikkat edilmesi gereken içerikler var. "
                "Bu doğrudan zararlı anlamına gelmez; ancak sık kullanım/tüketimde değerlendirilmelidir."
            )

        return {
            "title": risk_title(highest),
            "message": "\n\n".join(details + [general, "Nihai karar kullanıcıya aittir."]),
            "risk": highest,
            "read_text": text,
            "detected_items": shown
        }

    if not quality["can_be_low"]:
        return {
            "title": "⚠️ İçerik Net Okunamadı",
            "message": (
                "Metin okunabilir görünüyor fakat tam bir içerik listesi yakalanmadı. "
                "Daha güvenilir sonuç için İçindekiler/Ingredients alanını tekrar okutun."
            ),
            "risk": "unknown",
            "read_text": text,
            "detected_items": []
        }

    return {
        "title": "🟢 Düşük Risk",
        "message": (
            "Okunan içerik listesinde belirgin yüksek dikkat gerektiren veya hassasiyet açısından öne çıkan madde yakalanmadı.\n\n"
            "Bu sonuç yalnızca okunan metne göre bilgilendirme amaçlıdır. İçerik eksik okunduysa değerlendirme değişebilir."
        ),
        "risk": "low",
        "read_text": text,
        "detected_items": []
    }


def safe_json_loads(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
    return None


@app.post("/analyze-content")
async def analyze_content(data: ContentRequest):
    raw_text = normalize_text(data.text)
    content_text = extract_relevant_content(raw_text)
    quality = ocr_quality(content_text)
    has_image = bool((data.image or "").strip())

    fallback = local_content_analysis(content_text, quality)

    # Görsel yoksa ve OCR okunamadıysa risk rengi üretmek yerine unknown döndür.
    if fallback["risk"] == "unknown" and not has_image:
        return fallback

    try:
        user_content = [
            {
                "type": "text",
                "text": (
                    "Ürün arka etiketini analiz et.\n"
                    "Önce görseldeki İçindekiler/Ingredients alanını oku. "
                    "OCR metni yardımcıdır ama eksik olabilir; görseldeki etiketi esas al.\n\n"
                    f"Mobil OCR metni:\n{content_text or raw_text}"
                )
            }
        ]
        if has_image:
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{data.image}"
                }
            })

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
Sen 'İçinde Ne Var?' uygulamasının gıda ve kozmetik içerik analiz motorusun.

Kurallar:
- Tüm cevap Türkçe olacak.
- Kullanıcıya "al" veya "alma" deme.
- Kesin tıbbi hüküm verme.
- Nihai karar kullanıcıya ait olduğunu belirt.
- Sadece "madde var" deme; maddenin ne işe yaradığını ve sağlık açısından neden dikkat gerektirebileceğini açıkla.
- Görsel varsa OCR metnine bağlı kalma; ürün arka etiketindeki İçindekiler/Ingredients alanını görselden oku.
- Görselden okuduğun içerik listesini read_text alanına mümkün olduğunca tam yaz.
- Etikette 20-30 madde varsa sadece riskli olanları değil, iyi/nötr maddeleri de detected_items içinde risk="low" olarak döndür.
- OCR ve görsel birlikte yetersizse risk="unknown" döndür.
- Emin değilsen düşük risk verme.
- Düşük risk sadece içerik listesi net ve dikkat gerektiren madde görünmüyorsa verilir.
- Gıda için WHO/FAO JECFA, Codex GSFA, EFSA/FDA güvenlik yaklaşımı ve IARC sınıflandırma mantığını dikkate al.
- Kozmetik için paraben, SLS/SLES, alkol, fragrance/parfum, phenoxyethanol, formaldehyde salıcılar, triclosan, hydroquinone, methylisothiazolinone gibi hassasiyet/tartışmalı içerikleri önemse.

Risk:
high = güçlü dikkat gerektiren içerik.
medium = dikkat/hassasiyet gerektiren içerik.
low = net okunmuş ve belirgin dikkat gerektiren içerik yok.
unknown = net okunamadı veya içerik listesi eksik.

JSON dışında hiçbir şey yazma.
JSON:
{
  "title": "🔴/🟡/🟢/⚠️ kısa başlık",
  "risk": "high | medium | low | unknown",
  "read_text": "Görselden/OCR'dan okunan mümkün olan en tam içerik listesi",
  "message": "Detaylı ama sade açıklama. Önce önemli maddeleri açıkla: ne işe yarar, sağlık açısından ne anlama gelir. Sonra genel değerlendirme ve 'Nihai karar kullanıcıya aittir.' cümlesi.",
  "detected_items": [
    {
      "name": "Madde adı",
      "risk": "high | medium | low",
      "purpose": "Ne işe yarar?",
      "health_note": "Sağlık açısından değerlendirme"
    }
  ]
}
"""
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            temperature=0,
            max_tokens=1100
        )

        result_text = response.choices[0].message.content.strip()
        ai_result = safe_json_loads(result_text)

        if not ai_result:
            return fallback

        ai_risk = normalize_risk(ai_result.get("risk"))
        fallback_risk = fallback["risk"]
        read_text = normalize_text(ai_result.get("read_text") or content_text)
        read_quality = ocr_quality(extract_relevant_content(read_text))

        # AI, yerel motorun riskini düşüremez. OCR tamamen zayıfken görsel analizi bu kilidi açabilir.
        if fallback_risk != "unknown" and risk_rank(ai_risk) < risk_rank(fallback_risk):
            return fallback

        if ai_risk == "low" and not read_quality["can_be_low"]:
            return {
                "title": "⚠️ İçerik Net Okunamadı",
                "message": (
                    "İçerik listesi tam okunamadı. Düşük risk sonucu vermek için etiketin daha net okunması gerekir."
                ),
                "risk": "unknown",
                "read_text": read_text,
                "detected_items": []
            }

        return {
            "title": ai_result.get("title") or risk_title(ai_risk),
            "message": ai_result.get("message") or fallback["message"],
            "risk": ai_risk,
            "read_text": read_text,
            "detected_items": ai_result.get("detected_items", fallback.get("detected_items", []))
        }

    except Exception as e:
        return {
            **fallback,
            "debug": str(e)
        }



def parse_turkish_price(value) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value)
    s = s.replace("₺", "").replace("TL", "").replace("tl", "").strip()
    s = re.sub(r"[^0-9,\.]", "", s)

    if not s:
        return None

    # Türkiye formatı: 1.299,90
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except Exception:
        return None


def clean_product_query(text: str) -> str:
    clean = normalize_text(text)
    clean = re.sub(r"\b(içindekiler|icindekiler|ingredients|composition|besin değerleri|nutrition|üretici|son tüketim|tavsiye edilen)\b.*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"[^a-zA-ZğüşöçıİĞÜŞÖÇ0-9\s\-\.,]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    # Çok uzunsa ilk faydalı kısmı al.
    if len(clean) > 160:
        clean = clean[:160].strip()

    return clean


async def detect_product_for_price(data: PriceRequest) -> dict:
    text_query = clean_product_query(data.text)

    if data.image:
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """
Sen fiyat karşılaştırması için ürün tespit motorusun.
Fotoğraf ve OCR metninden ürün adını, marka/gramaj/model bilgisini çıkar.
Gıda, kozmetik veya küçük ev eşyası olabilir.
Kesin değilse en olası kısa arama sorgusunu üret.
JSON dışında hiçbir şey yazma.

JSON:
{
  "query": "Market veya Google Shopping araması için net ürün adı + gramaj/model",
  "product_name": "Kullanıcıya gösterilecek ürün adı",
  "confidence": "high | medium | low"
}
"""
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"OCR metni: {text_query}\nBu ürün için fiyat karşılaştırma arama sorgusu üret."
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
                temperature=0,
                max_tokens=200
            )

            parsed = safe_json_loads(response.choices[0].message.content.strip())
            if parsed and parsed.get("query"):
                return {
                    "query": clean_product_query(parsed.get("query", "")),
                    "product_name": parsed.get("product_name") or parsed.get("query"),
                    "confidence": parsed.get("confidence", "medium")
                }
        except Exception:
            pass

    return {
        "query": text_query,
        "product_name": text_query or "Ürün",
        "confidence": "medium" if len(text_query) >= 5 else "low"
    }


def serpapi_google_shopping(query: str) -> list[dict]:
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return []

    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": api_key,
        "hl": "tr",
        "gl": "tr",
        "google_domain": "google.com.tr",
        "location": "Turkey",
        "num": "20",
    }

    url = "https://serpapi.com/search?" + urllib.parse.urlencode(params)

    with urllib.request.urlopen(url, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))

    results = payload.get("shopping_results") or []

    clean_results = []
    for item in results:
        price = item.get("extracted_price")
        if price is None:
            price = parse_turkish_price(item.get("price"))

        if price is None:
            continue

        title = item.get("title") or "Ürün"
        source = item.get("source") or item.get("seller") or "Satıcı"
        link = item.get("link") or item.get("product_link") or ""

        clean_results.append({
            "title": title,
            "source": source,
            "price": float(price),
            "price_text": item.get("price") or f"{price:.2f} TL",
            "link": link
        })

    clean_results.sort(key=lambda x: x["price"])
    return clean_results[:8]


def build_price_message(product_name: str, query: str, results: list[dict]) -> dict:
    if not results:
        return {
            "title": "💰 Fiyat Bilgisi Bulunamadı",
            "message": (
                f"Ürün: {product_name or query}\n"
                "Karşılaştırılabilir güncel fiyat bulunamadı. Ürün adı, marka, gramaj veya etiket daha net okutulursa sonuç iyileşir."
            ),
            "risk": "unknown",
            "price_status": "unknown",
            "summary": {
                "product_name": product_name or query,
                "store_count": 0,
                "lowest_price": None,
                "average_price": None,
                "highest_price": None,
                "saving_amount": None,
                "saving_percent": None,
                "best_store": None,
                "note": "Fiyat bulunamadı."
            },
            "prices": []
        }

    prices = [r["price"] for r in results]
    lowest = results[0]
    average = sum(prices) / len(prices)
    highest = max(prices)
    saving_amount = max(0.0, average - lowest["price"])
    saving_percent = (saving_amount / average * 100) if average > 0 else 0.0

    if lowest["price"] <= average * 0.90:
        risk = "low"
        price_status = "good"
        title = "🟢 Uygun Fiyat"
        comment = "Bulunan en düşük fiyat piyasa ortalamasının altında görünüyor."
    elif lowest["price"] <= average * 1.05:
        risk = "medium"
        price_status = "normal"
        title = "🟡 Ortalama Fiyat"
        comment = "Bulunan fiyatlar piyasa ortalamasına yakın görünüyor."
    else:
        risk = "high"
        price_status = "expensive"
        title = "🔴 Yüksek Fiyat"
        comment = "Bulunan fiyatlar ortalamanın üzerinde görünüyor."

    lines = [
        f"Ürün: {product_name or query}",
        f"{len(results)} mağaza sonucu karşılaştırıldı.",
        f"En uygun: {lowest['source']} - {lowest['price']:.2f} TL",
        f"Ortalama: {average:.2f} TL",
        f"En yüksek: {highest:.2f} TL",
        f"Tasarruf: yaklaşık {saving_amount:.2f} TL (%{saving_percent:.0f})",
        f"Kısa yorum: {comment}",
        "Not: Fiyatlar anlık arama sonuçlarına göre değişebilir."
    ]

    return {
        "title": title,
        "product_name": product_name,
        "detected_product": product_name,
        "message": "\n".join(lines),
        "risk": risk,
        "price_status": price_status,
        "summary": {
            "product_name": product_name or query,
            "store_count": len(results),
            "lowest_price": round(lowest["price"], 2),
            "average_price": round(average, 2),
            "highest_price": round(highest, 2),
            "saving_amount": round(saving_amount, 2),
            "saving_percent": round(saving_percent, 1),
            "best_store": lowest["source"],
            "note": comment
        },
        "prices": results
    }


@app.post("/analyze-price")
async def analyze_price(data: PriceRequest):
    detected = await detect_product_for_price(data)
    query = detected.get("query", "").strip()
    product_name = detected.get("product_name", query)

    if len(query) < 3:
        return {
            "title": "💰 Ürün Net Algılanamadı",
            "message": (
                "Fiyat karşılaştırması için ürün adı, marka veya gramaj net algılanamadı. "
                "Ürünün ön yüzünü, barkodunu veya fiyat etiketini daha net göstererek tekrar deneyin."
            ),
            "risk": "unknown",
            "query": query,
            "prices": []
        }

    try:
        results = serpapi_google_shopping(query)
        output = build_price_message(product_name, query, results)
        output["query"] = query
        output["confidence"] = detected.get("confidence", "medium")
        return output

    except Exception as e:
        return {
            "title": "💰 Fiyat Analizi Tamamlanamadı",
            "message": (
                "Fiyat karşılaştırması sırasında bağlantı veya API tarafında sorun oluştu. "
                "Render ortamında SERPAPI_API_KEY tanımlı olduğundan emin olun."
            ),
            "risk": "unknown",
            "query": query,
            "debug": str(e),
            "prices": []
        }




# Besin tarafı: içerik analizi gibi güçlü, JSON tabanlı ve panel dostu çıktı üretir.
def nutrition_score_from_risk(risk: str) -> int:
    risk = normalize_risk(risk)
    if risk == "low":
        return 78
    if risk == "medium":
        return 52
    if risk == "high":
        return 24
    return 0


def normalize_nutrition_payload(parsed: dict) -> dict:
    risk = normalize_risk(parsed.get("risk", "medium")) if parsed else "medium"
    nutrition = parsed.get("nutrition") if isinstance(parsed.get("nutrition"), dict) else {}
    alerts = parsed.get("alerts") if isinstance(parsed.get("alerts"), list) else []
    audience_notes = parsed.get("audience_notes") if isinstance(parsed.get("audience_notes"), dict) else {}
    product_name = str(
        parsed.get("product_name")
        or parsed.get("detected_food")
        or parsed.get("detected_product")
        or ""
    ).strip()
    technical_words = ["openai", "api", "logs", "debug", "console", "terminal"]
    if any(word in product_name.lower() for word in technical_words):
        product_name = ""


    try:
        score = int(parsed.get("score"))
    except Exception:
        score = nutrition_score_from_risk(risk)
    score = max(0, min(100, score))

    defaults = {
        "calories": "Belirsiz",
        "protein": "Belirsiz",
        "carbohydrate": "Belirsiz",
        "fat": "Belirsiz",
        "sugar": "Belirsiz",
        "fiber": "Belirsiz",
        "salt": "Belirsiz",
    }
    for key, value in defaults.items():
        nutrition[key] = str(nutrition.get(key) or value)

    portion = str(parsed.get("portion") or "Belirsiz")
    nova = str(parsed.get("nova") or "Belirsiz")
    confidence = str(parsed.get("confidence") or "medium")
    title = parsed.get("title") or "🟡 Besin Analizi"

    if not alerts:
        alerts = ["Besin değerleri görselden tahmini olarak hesaplandı."]

    message = parsed.get("message") or (
        f"Porsiyon: {portion}\n"
        f"Kalori: {nutrition['calories']}\n"
        f"Protein: {nutrition['protein']}\n"
        f"Karbonhidrat: {nutrition['carbohydrate']}\n"
        f"Yağ: {nutrition['fat']}\n"
        f"Şeker: {nutrition['sugar']}\n"
        f"Lif: {nutrition['fiber']}\n"
        f"Tuz: {nutrition['salt']}\n"
        f"Kısa yorum: {alerts[0]}"
    )

    return {
        "title": title,
        "message": message,
        "risk": risk,
        "score": score,
        "portion": portion,
        "nova": nova,
        "confidence": confidence,
        "nutrition": nutrition,
        "alerts": alerts[:6],
        "audience_notes": {
            "children": audience_notes.get("children", "Porsiyon ve tüketim sıklığına dikkat edilmelidir."),
            "diabetes": audience_notes.get("diabetes", "Şeker/karbonhidrat miktarı kişisel duruma göre değerlendirilmelidir."),
            "sport": audience_notes.get("sport", "Protein ve enerji ihtiyacına göre değerlendirilmelidir."),
            "weight_control": audience_notes.get("weight_control", "Porsiyon kontrolü önemlidir.")
        }
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
Sen "İçinde Ne Var?" uygulamasının profesyonel besin analizi motorusun.

Görev:
- Görseldeki yiyeceği önce tanımla. Yumurta görüyorsan "yumurta", et görüyorsan "et", çay görüyorsan "çay", pilav, makarna, salata vb. ne görünüyorsa product_name alanına yaz.
- Gıda dışı ekran yazıları, bilgisayar ekranı, OpenAI, API, log, terminal, console metinleri ürün veya gıda adı değildir; bunları product_name olarak yazma.
- Tabak veya gıda fotoğrafı için OCR metnine güvenme; görselde görünen yiyeceği esas al.
- Tek bir gıdadan emin değilsen "karışık tabak" veya "gıda analizi" yaz ve confidence="low" döndür.
- Görüntüdeki yemeği, öğünü, paketli ürünü veya besin değerleri tablosunu analiz et.
- Kesin laboratuvar sonucu gibi konuşma; tahmini olduğunu açıkça belirt.
- Görsel belirsizse risk="unknown" döndür ve düşük risk verme.
- Porsiyon tahmini yap. Porsiyon belirsizse aralık ver.
- Kullanıcı dostu, kısa ama dolu Türkçe çıktı üret.
- JSON dışında hiçbir şey yazma.

Değerlendirme mantığı:
- Kalori yoğunluğu, protein kalitesi, karbonhidrat/şeker yükü, yağ oranı, lif ve tuz dengesini birlikte değerlendir.
- Çok şekerli, çok yağlı, lif/protein düşük veya yoğun işlenmiş görünen ürünlerde skor düşük olmalı.
- Tabak/yemek fotoğrafında değerler tahmini olmalı; besin etiketi görülüyorsa etiketi öncelikle kullan.
- NOVA sınıfını tahmini ver: 1 doğal/minimal, 2 işlenmiş mutfak bileşeni, 3 işlenmiş, 4 ultra işlenmiş. Emin değilsen "Belirsiz" yaz.
- Çocuklar, diyabet, sporcu ve kilo kontrolü için kısa not üret.

Zorunlu JSON:
{
  "title": "kısa başlık",
  "product_name": "Görselde tanımlanan gıda veya tabak adı",
  "risk": "low | medium | high | unknown",
  "score": 0-100,
  "portion": "Tahmini porsiyon",
  "nova": "NOVA 1 | NOVA 2 | NOVA 3 | NOVA 4 | Belirsiz",
  "confidence": "high | medium | low",
  "nutrition": {
    "calories": "... kcal",
    "protein": "... g",
    "carbohydrate": "... g",
    "fat": "... g",
    "sugar": "... g veya belirsiz",
    "fiber": "... g veya belirsiz",
    "salt": "... g veya belirsiz"
  },
  "alerts": ["Kısa uyarı 1", "Kısa uyarı 2"],
  "audience_notes": {
    "children": "Çocuklar için kısa not",
    "diabetes": "Diyabet/kan şekeri için kısa not",
    "sport": "Sporcu/protein açısından kısa not",
    "weight_control": "Kilo kontrolü için kısa not"
  },
  "message": "Porsiyon: ...\nKalori: ...\nProtein: ...\nKarbonhidrat: ...\nYağ: ...\nŞeker: ...\nLif: ...\nTuz: ...\nKısa yorum: ...\nDikkat: ..."
}
"""
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Bu görüntüyü besin değeri açısından analiz et. Görsel belirsizse bunu açıkça belirt."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{data.image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=900,
            temperature=0.1
        )

        result_text = response.choices[0].message.content.strip()
        parsed = safe_json_loads(result_text)

        if not parsed:
            return normalize_nutrition_payload({
                "title": "🟡 Besin Analizi",
                "message": result_text,
                "risk": "medium",
                "score": 50,
                "nutrition": {},
                "alerts": ["Model yapılandırılmış JSON döndürmedi; sonuç tahmini olarak gösterildi."]
            })

        return normalize_nutrition_payload(parsed)

    except Exception as e:
        return normalize_nutrition_payload({
            "title": "🟡 Besin Analizi Tamamlanamadı",
            "message": f"Besin analizi şu anda tamamlanamadı. Hata: {str(e)}",
            "risk": "medium",
            "score": 50,
            "nutrition": {},
            "alerts": ["Bağlantı veya analiz sırasında sorun oluştu."]
        })

