"""İçinde Ne Var backend uygulaması.

Sistem/Firebase/AI akışları ve API endpointleri bu dosyada; ürün güvenlik
verileri alan bazlı katalog dosyalarında tutulur.
"""

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()


import os

from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

from pydantic import BaseModel

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

from collections import defaultdict, deque
from datetime import datetime, timezone
from time import monotonic
import json
import os

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials, firestore
from fastapi import Depends, Header, HTTPException

def initialize_firebase_admin():
    project_id = os.getenv("FIREBASE_PROJECT_ID", "icinde-ne-var-af6cd")
    raw_service_account = (
        os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.getenv("FIREBASE_CREDENTIALS_JSON")
    )

    if raw_service_account:
        try:
            service_account = json.loads(raw_service_account)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "FIREBASE_SERVICE_ACCOUNT_JSON geçerli bir JSON değil."
            ) from exc

        private_key = str(service_account.get("private_key") or "")
        if private_key:
            service_account["private_key"] = private_key.replace("\\n", "\n")
        credential = credentials.Certificate(service_account)
        return firebase_admin.initialize_app(
            credential,
            options={"projectId": project_id},
        )

    # Google Cloud gibi ADC sağlayan ortamlarda veya Render Secret File ile
    # GOOGLE_APPLICATION_CREDENTIALS ayarlandığında bu yol kullanılır.
    return firebase_admin.initialize_app(options={"projectId": project_id})


initialize_firebase_admin()

REQUEST_LIMIT = int(os.getenv("REQUEST_LIMIT_PER_MINUTE", "20"))
DAILY_ANALYSIS_LIMIT = int(os.getenv("DAILY_ANALYSIS_LIMIT", "5"))
request_windows: dict[str, deque[float]] = defaultdict(deque)
firestore_client = firestore.client()


def reserve_analysis_right(uid: str, mode: str) -> dict:
    """Atomically reserve one analysis right on the server."""
    user_ref = firestore_client.collection("users").document(uid)
    usage_ref = firestore_client.collection("usage").document(uid)
    transaction = firestore_client.transaction()

    @firestore.transactional
    def reserve(txn):
        user_data = user_ref.get(transaction=txn).to_dict() or {}
        expires_at = user_data.get("premiumExpiresAt")
        premium_not_expired = (
            isinstance(expires_at, datetime)
            and expires_at > datetime.now(timezone.utc)
        )
        if user_data.get("isPremium") is True and premium_not_expired:
            return {"isPremium": True, "mode": mode}
        if user_data.get("isPremium") is True and not premium_not_expired:
            txn.set(user_ref, {
                "isPremium": False,
                "subscriptionState": "EXPIRED_LOCAL_CHECK",
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }, merge=True)

        snap = usage_ref.get(transaction=txn)
        data = snap.to_dict() or {}
        now_ms = int(__import__("time").time() * 1000)
        reset_at = int(data.get("resetAtMillis") or 0)
        if reset_at <= now_ms:
            data = {
                "contentUsed": 0,
                "nutritionUsed": 0,
                "priceUsed": 0,
                "rewardCredits": int(data.get("rewardCredits") or 0),
                "resetAtMillis": now_ms + 24 * 60 * 60 * 1000,
            }

        field = f"{mode}Used"
        used = int(data.get(field) or 0)
        credits = max(0, int(data.get("rewardCredits") or 0))
        if used >= DAILY_ANALYSIS_LIMIT:
            if credits <= 0:
                raise HTTPException(
                    status_code=429,
                    detail="Günlük analiz hakkınız doldu.",
                )
            data["rewardCredits"] = credits - 1

        data[field] = used + 1
        data.update({
            "uid": uid,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        if not snap.exists:
            data["createdAt"] = firestore.SERVER_TIMESTAMP
        txn.set(usage_ref, data, merge=True)
        return {"isPremium": False, "mode": mode, **data}

    return reserve(transaction)


async def require_firebase_user(
    authorization: str | None = Header(default=None),
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli.")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli.")

    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Geçersiz oturum.") from None

    uid = str(decoded.get("uid") or decoded.get("sub") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Geçersiz kullanıcı.")

    now = monotonic()
    window = request_windows[uid]
    while window and now - window[0] >= 60:
        window.popleft()
    if len(window) >= REQUEST_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla istek gönderildi. Lütfen biraz bekleyin.",
        )
    window.append(now)
    return decoded


async def require_content_right(
    user: dict = Depends(require_firebase_user),
) -> dict:
    reserve_analysis_right(str(user.get("uid") or user.get("sub")), "content")
    return user


async def require_nutrition_right(
    user: dict = Depends(require_firebase_user),
) -> dict:
    reserve_analysis_right(str(user.get("uid") or user.get("sub")), "nutrition")
    return user


async def require_price_right(
    user: dict = Depends(require_firebase_user),
) -> dict:
    reserve_analysis_right(str(user.get("uid") or user.get("sub")), "price")
    return user

app = FastAPI(title="İçinde Ne Var API")

import json
import os
import re
from time import monotonic

from fastapi import APIRouter, Depends

from food_safety_catalog import normalized_food_risk, unknown_e_codes
from safety_catalog_registry import SAFETY_ALIASES, SAFETY_ITEMS


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
        "formula", "formül", "formul",
        "zutaten", "inhaltsstoffe", "bestandteile",
        "ingrédients", "ingredients", "composition",
        "成分", "配料", "原料", "原材料"
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
        "art no", "batch", "lot",
        "hersteller", "mindestens haltbar", "haltbar bis", "aufbewahrung",
        "fabriqué par", "distribué par", "à consommer", "conservation",
        "制造商", "经销商", "保质期", "生产日期", "净含量"
    ]

    stop_index = -1
    for keyword in stop_keywords:
        idx = lower_extracted.find(keyword)
        if idx > 40 and (stop_index == -1 or idx < stop_index):
            stop_index = idx

    if stop_index != -1:
        extracted = extracted[:stop_index]

    return extracted[:12000].strip()


def ocr_quality(text: str) -> dict:
    clean = normalize_text(text)
    lower = clean.lower()

    letters = re.findall(r"[a-zA-ZğüşöçıİĞÜŞÖÇ]", clean)
    comma_like = clean.count(",") + clean.count(";")
    has_content_keyword = any(
        k in lower for k in [
            "içindekiler", "icindekiler", "ingredients", "composition",
            "contents", "inci", "bileşenler", "bilesenler",
            "zutaten", "inhaltsstoffe", "ingrédients",
            "成分", "配料", "原材料"
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
TERM_INFO = dict(SAFETY_ITEMS)
TERM_ALIASES = dict(SAFETY_ALIASES)

for alias, canonical in TERM_ALIASES.items():
    if canonical in TERM_INFO:
        TERM_INFO[alias] = TERM_INFO[canonical]


def find_terms(text: str) -> list[dict]:
    lower = text.lower()
    found = []
    seen_names = set()

    # Uzun terimleri önce yakalamak için sıralama.
    for key in sorted(TERM_INFO.keys(), key=len, reverse=True):
        pattern = (
            r"(?<![\w])"
            + re.escape(key.lower())
            + r"(?![\w])"
        )
        if re.search(pattern, lower):
            item = TERM_INFO[key]
            if item["name"] not in seen_names:
                found.append(item)
                seen_names.add(item["name"])

    if any(item.get("name", "").startswith("Endüstriyel trans yağ") for item in found):
        found = [
            item for item in found
            if item.get("name") != "Hidrojene yağ"
        ]
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


def response_language_name(language: str) -> str:
    code = (language or "tr").lower().strip()
    if code.startswith("en"):
        return "English"
    if code.startswith("de"):
        return "Deutsch"
    if code.startswith("fr"):
        return "Français"
    if code.startswith("zh") or code.startswith("cn"):
        return "中文"
    return "Türkçe"
def response_language_code(language: str) -> str:
    code = (language or "tr").lower().strip()
    if code.startswith("en"):
        return "en"
    if code.startswith("de"):
        return "de"
    if code.startswith("fr"):
        return "fr"
    if code.startswith("zh") or code.startswith("cn"):
        return "zh"
    return "tr"


def risk_title(risk: str) -> str:
    if risk == "high":
        return "🔴 Yüksek Dikkat"
    if risk == "low":
        return "🟢 Düşük Risk"
    return "🟡 Dikkat Gerektirir"


def neutral_ingredient_names(text: str) -> list[str]:
    clean = normalize_text(text)
    clean = re.sub(
        r"^\s*(içindekiler|icindekiler|ingredients?|contents|bileşenler|bilesenler|zutaten|ingrédients)\s*:?\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    candidates = re.split(r"[,;•\n]", clean)
    risky_patterns = [
        re.compile(r"(?<![\w])" + re.escape(key.lower()) + r"(?![\w])")
        for key in TERM_INFO
    ]
    result = []
    seen = set()
    for candidate in candidates:
        name = normalize_text(candidate).strip(" .:-")
        lower = name.lower()
        if len(name) < 2 or len(name) > 70:
            continue
        if re.search(r"\d{2,}", name):
            continue
        if any(pattern.search(lower) for pattern in risky_patterns):
            continue
        if lower in seen:
            continue
        seen.add(lower)
        result.append(name)
    return result


def categorized_content_items(found: list[dict], text: str) -> dict:
    good_items = neutral_ingredient_names(text)
    good_items.extend(
        item["name"] for item in found
        if normalize_risk(item.get("risk")) == "low"
        and item["name"] not in good_items
    )
    return {
        "good_items": good_items,
        "warning_items": [
            item["name"] for item in found
            if normalize_risk(item.get("risk")) == "medium"
        ],
        "avoid_items": [
            item["name"] for item in found
            if normalize_risk(item.get("risk")) == "high"
        ],
    }


def local_content_analysis(text: str, quality: dict) -> dict:
    found = find_terms(text)
    for code in unknown_e_codes(text):
        found.append({
            "name": f"{code} - Katalog doğrulaması gerekli",
            "risk": "medium",
            "purpose": "Etikette bir katkı kodu olarak yer alıyor.",
            "effect": (
                "Bu kod yerel WHO/JECFA kataloğunda henüz eşleşmedi; "
                "otomatik olarak düşük risk verilmez."
            ),
        })

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
        shown = found
        categories = categorized_content_items(shown, text)

        details = []
        for item in shown[:6]:
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
            "message": "\n\n".join(details + [
                general,
                "Bu değerlendirme etiketteki madde varlığına dayanır; miktar bilinmediği için ADI aşımı göstermez.",
                "Nihai karar kullanıcıya aittir.",
            ]),
            "risk": highest,
            "read_text": text,
            "detected_items": shown,
            **categories,
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
        "title": "ğŸŸ¢ Düşük Risk",
        "message": (
            "Okunan içerik listesinde belirgin yüksek dikkat gerektiren veya hassasiyet açısından öne çıkan madde yakalanmadı.\n\n"
            "Bu sonuç yalnızca okunan metne göre bilgilendirme amaçlıdır. İçerik eksik okunduysa değerlendirme değişebilir. "
            "Miktar bilinmediği için ADI aşımı göstermez."
        ),
        "risk": "low",
        "read_text": text,
        "detected_items": [],
        "good_items": neutral_ingredient_names(text),
        "warning_items": [],
        "avoid_items": [],
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


def is_instruction_or_warning_text(value: str) -> bool:
    lower = normalize_text(value).lower().translate(str.maketrans({
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    }))
    if not lower:
        return True
    if lower in {"yuz", "goz", "cilt", "eller", "el"}:
        return True

    instruction_phrases = [
        "kisinin bilinci", "bilinci acik", "ilk yardim",
        "goz ile temas", "gozle temas", "derhal", "doktor",
        "zehir danisma", "iyice karistir", "kullanmadan once",
        "kullanim talimat", "durulayin", "cocuklarin ulasamayacagi",
        "eldiven kullan", "yutulmasi halinde", "paslanmaz celik",
        "uygun degildir", "sadece kullanim", "gida maddelerinden uzakta",
        "gida madde", "kullanma", "takili ve", "yapmasi kolaysa",
        "ciddi goz hasarina", "ciddi goz tahrisine", "kontakt lens",
        "koruyucu eldiven", "koruyucu gozluk", "solunmasi halinde",
    ]
    if any(phrase in lower for phrase in instruction_phrases):
        return True

    instruction_verbs = [
        "uygulayin", "bekletin", "temizleyin", "karistirin",
        "kullaniniz", "saklayiniz", "basvurun", "cikarin",
    ]
    return any(verb in lower for verb in instruction_verbs)


def detected_item_identity(name: str) -> str:
    lower = str(name or "").lower().strip()
    for alias in sorted(SAFETY_ALIASES, key=len, reverse=True):
        pattern = r"(?<![\w])" + re.escape(alias.lower()) + r"(?![\w])"
        if re.search(pattern, lower):
            return f"catalog:{SAFETY_ALIASES[alias]}"
    return re.sub(r"[^a-z0-9çğıöşü]+", " ", lower).strip()


def merge_detected_items(ai_items, *texts: str) -> list[dict]:
    merged = []
    seen = set()

    if isinstance(ai_items, list):
        for item in ai_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or is_instruction_or_warning_text(name):
                continue
            key = detected_item_identity(name)
            if key in seen:
                continue
            normalized_item = dict(item)
            normalized_item["risk"] = normalized_food_risk(
                name,
                normalize_risk(str(item.get("risk", ""))),
            )
            merged.append(normalized_item)
            seen.add(key)

    combined_text = "\n".join([str(text or "") for text in texts])
    for item in find_terms(combined_text):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = detected_item_identity(name)
        if key in seen:
            for existing in merged:
                if detected_item_identity(existing.get("name") or "") != key:
                    continue
                if risk_rank(item.get("risk", "")) > risk_rank(existing.get("risk", "")):
                    existing["risk"] = item.get("risk", "medium")
                    existing["purpose"] = item.get("purpose", "")
                    existing["health_note"] = item.get("effect", "")
                break
            continue
        merged.append({
            "name": name,
            "risk": item.get("risk", "medium"),
            "purpose": item.get("purpose", ""),
            "health_note": item.get("effect", "")
        })
        seen.add(key)

    return merged


def highest_risk_from_items(items: list[dict], fallback_risk: str) -> str:
    risks = [normalize_risk(str(item.get("risk", ""))) for item in items if isinstance(item, dict)]
    risks.append(normalize_risk(fallback_risk))
    return max(risks, key=risk_rank)


def localized_analysis_unavailable(language_code: str, read_text: str = "") -> dict:
    messages = {
        "en": (
            "Analysis could not be completed clearly. Please scan the ingredients area again with better lighting. "
            "The final decision belongs to the user."
        ),
        "de": (
            "Die Analyse konnte nicht eindeutig abgeschlossen werden. Bitte scannen Sie den Zutatenbereich bei besserem Licht erneut. "
            "Die endgültige Entscheidung liegt beim Nutzer."
        ),
        "fr": (
            "L’analyse n’a pas pu être terminée clairement. Veuillez rescanner la zone des ingrédients avec un meilleur éclairage. "
            "La décision finale appartient à l’utilisateur."
        ),
        "zh": "分析未能清晰完成。请在更好的光线下重新扫描成分区域。最终决定由用户自行作出。",
    }
    titles = {
        "en": "Analysis incomplete",
        "de": "Analyse unvollständig",
        "fr": "Analyse incomplète",
        "zh": "分析未完成",
    }
    return {
        "title": titles.get(language_code, "Analiz tamamlanamadı"),
        "message": messages.get(
            language_code,
            "Analiz net tamamlanamadı. Daha iyi ışıkta içerik alanını tekrar okutun. Nihai karar kullanıcıya aittir.",
        ),
        "risk": "unknown",
        "read_text": read_text,
        "detected_items": [],
    }


@app.post("/analyze-content")
async def analyze_content(
    data: ContentRequest,
    _user: dict = Depends(require_content_right),
):
    raw_text = normalize_text(data.text)
    content_text = extract_relevant_content(raw_text)
    quality = ocr_quality(content_text)
    has_image = bool((data.image or "").strip())
    requested_language = response_language_code(data.language)
    response_language = response_language_name(data.language)

    fallback = local_content_analysis(content_text, quality)
    fallback["analysis_source"] = "local"

    # Görsel yoksa ve OCR okunamadıysa risk rengi üretmek yerine unknown döndür.
    if requested_language == "tr" and fallback["risk"] == "unknown" and not has_image:
        return fallback

    if (
        requested_language == "tr"
        and fallback.get("risk") != "unknown"
        and quality.get("can_be_low")
        and len(fallback.get("detected_items", [])) >= 3
    ):
        return fallback

    try:
        user_content = [
            {
                "type": "text",
                "text": (
                    "Ürün arka etiketini analiz et. Ürün gıda, kozmetik/kişisel bakım veya temizlik ürünü olabilir.\n"
                    "Önce görseldeki İçindekiler/Ingredients/Composition/Bileşenler alanını oku. "
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
Sen 'İçinde Ne Var?' uygulamasının gıda, kozmetik/kişisel bakım ve temizlik ürünü içerik analiz motorusun.

Kurallar:
- Tüm cevap __RESPONSE_LANGUAGE__ olacak.
- JSON içindeki title, message, detected_items[].name, detected_items[].purpose ve detected_items[].health_note alanlarının tamamı __RESPONSE_LANGUAGE__ olacak.
- Etiket veya OCR metni Türkçe olsa bile kullanıcı dili __RESPONSE_LANGUAGE__ ise madde adlarını ve açıklamaları __RESPONSE_LANGUAGE__ diline çevir.
- E kodları, katkı kodları ve teknik kimlikler korunabilir; ancak kullanıcıya görünen açıklama dili __RESPONSE_LANGUAGE__ kalacak.
- Kullanıcıya "al" veya "alma" deme.
- Kesin tıbbi hüküm verme.
- Nihai karar kullanıcıya ait olduğunu belirt.
- İçerik miktarı bilinmiyorsa ADI'nın aşıldığını iddia etme; değerlendirmenin yalnız etiket varlığına dayandığını açıkça belirt.
- Bir katkı maddesini yalnız E/INS kodu taşıdığı için high yapma.
- JECFA tarafından sayısal ADI verilmiş, miktara bağlı veya WHO tüketim azaltma önerisi bulunan maddeleri genel olarak medium değerlendir.
- JECFA'nın ADI "not specified" değerlendirmesi yaptığı maddeleri, başka özel risk yoksa low/bilgi olarak değerlendir.
- Aspartam/E951, asesülfam K/E950, sukraloz/E955, sakarin/E954, siklamat/E952 ve steviol glikozitleri/E960 high değil medium olmalıdır; fenilketonüride aspartam için özel uyarı ver.
- MSG/E621 high değildir; toplam sodyum ve kişisel hassasiyet için bilgi ver.
- E330, E300, E301, E302, E322, E331, E410, E412, E415, E440, E471, E500 ve E551 başka özel risk yoksa low/bilgi grubundadır.
- E200-E203, E210-E213, E220-E228, E249-E252, E320-E321, E338-E341, E407, E445, E450-E452 medium grubundadır.
- Şeker, glikoz/fruktoz/mısır şurubu yalnız var diye high değildir; miktar bilinmiyorsa medium değerlendir.
- Genel "hidrojene yağ" ifadesini medium; "kısmen hidrojene" veya endüstriyel trans yağı high değerlendir.
- Gıda için high kategorisini endüstriyel trans yağ gibi açık kaçınma durumlarına ayır. Bölgesel mevzuat farkını sağlık riskiyle karıştırma.
- Sadece "madde var" deme; maddenin ne işe yaradığını ve sağlık açısından neden dikkat gerektirebileceğini açıkla.
- Görsel varsa OCR metnine bağlı kalma; ürün arka etiketindeki İçindekiler/Ingredients alanını görselden oku.
- Görselden okuduğun içerik listesini read_text alanına mümkün olduğunca tam yaz.
- Etikette 20-30 madde varsa sadece riskli olanları değil, iyi/nötr maddeleri de detected_items içinde risk="low" olarak döndür.
- OCR ve görsel birlikte yetersizse risk="unknown" döndür.
- Emin değilsen düşük risk verme.
- Düşük risk sadece içerik listesi net ve dikkat gerektiren madde görünmüyorsa verilir.
- Gıda için WHO/FAO JECFA, Codex GSFA, EFSA/FDA güvenlik yaklaşımı ve IARC sınıflandırma mantığını dikkate al.
- Kozmetik için paraben, SLS/SLES, alkol, fragrance/parfum, phenoxyethanol, formaldehyde salıcılar, triclosan, hydroquinone, methylisothiazolinone gibi hassasiyet/tartışmalı içerikleri önemse.
- Temizlik ürünlerinde sodyum hipoklorit/aktif klor, sodyum hidroksit, amonyak, güçlü asitler ve benzalkonyum klorür gibi korozif veya güçlü tahriş edici maddeleri high olarak değerlendir.
- Anyonik/noniyonik yüzey aktif maddeler, parfüm, enzimler ve hidrojen peroksit gibi bileşenleri ürün yoğunluğu ve temas riski açısından medium olarak değerlendir.
- Klorlu ürünlerin asit veya amonyakla karıştırılmaması gerektiğini kritik güvenlik uyarısı olarak belirt.
- Kullanım talimatı, ilk yardım cümlesi, yüzey uyumluluğu, saklama uyarısı ve "iyice karıştırın" gibi emir cümlelerini içerik maddesi olarak detected_items listesine ekleme.

Risk:
high = güçlü dikkat gerektiren içerik.
medium = dikkat/hassasiyet gerektiren içerik.
low = net okunmuş ve belirgin dikkat gerektiren içerik yok.
unknown = net okunamadı veya içerik listesi eksik.

JSON dışında hiçbir şey yazma.
JSON:
{
  "title": "ğŸ”´/ğŸŸ¡/ğŸŸ¢/⚠️ kısa başlık",
  "risk": "high | medium | low | unknown",
  "read_text": "Görselden/OCR'dan okunan mümkün olan en tam içerik listesi",
  "message": "Detaylı ama sade açıklama. Önce önemli maddeleri açıkla: ne işe yarar, sağlık açısından ne anlama gelir. Sonra genel değerlendirme ve 'Nihai karar kullanıcıya aittir.' cümlesi.",
  "detected_items": [
    {
      "name": "Madde adı, kullanıcı diline çevrilmiş",
      "risk": "high | medium | low",
      "purpose": "Ne işe yarar? Kullanıcı dilinde yaz.",
      "health_note": "Sağlık açısından değerlendirme. Kullanıcı dilinde yaz."
    }
  ]
}
""".replace("__RESPONSE_LANGUAGE__", response_language)
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            temperature=0,
            max_tokens=2400
        )

        result_text = response.choices[0].message.content.strip()
        ai_result = safe_json_loads(result_text)

        if not ai_result:
            if requested_language != "tr":
                return localized_analysis_unavailable(requested_language, content_text)
            return fallback

        ai_risk = normalize_risk(ai_result.get("risk"))
        fallback_risk = fallback["risk"]
        read_text = normalize_text(ai_result.get("read_text") or content_text)
        read_quality = ocr_quality(extract_relevant_content(read_text))

        # AI, yerel motorun riskini düşüremez. OCR tamamen zayıfken görsel analizi bu kilidi açabilir.
        if (
            requested_language == "tr"
            and fallback_risk != "unknown"
            and risk_rank(ai_risk) < risk_rank(fallback_risk)
        ):
            return fallback

        if requested_language == "tr" and ai_risk == "low" and not read_quality["can_be_low"]:
            return {
                "title": "⚠️ İçerik Net Okunamadı",
                "message": (
                    "İçerik listesi tam okunamadı. Düşük risk sonucu vermek için etiketin daha net okunması gerekir."
                ),
                "risk": "unknown",
                "read_text": read_text,
                "detected_items": []
            }

        if requested_language == "tr":
            detected_items = merge_detected_items(
                ai_result.get("detected_items", []),
                content_text,
                read_text
            )
        else:
            detected_items = merge_detected_items(ai_result.get("detected_items", []))
        risk_floor = fallback_risk if fallback_risk != "unknown" else ai_risk
        final_risk = highest_risk_from_items(detected_items, risk_floor)

        return {
            "title": (
                risk_title(final_risk)
                if requested_language == "tr"
                else ai_result.get("title") or risk_title(final_risk)
            ),
            "message": ai_result.get("message") or fallback["message"],
            "risk": final_risk,
            "read_text": read_text,
            "detected_items": detected_items,
            "analysis_source": "ai"
        }

    except Exception:
        return fallback

import json
import re
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends



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

def marketfiyati_search(query: str) -> list[dict]:
    body = {
        "keywords": query,
        "pages": 0,
        "size": 40,
    }

    request = urllib.request.Request(
        "https://api.marketfiyati.org.tr/api/v2/search",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Origin": "https://marketfiyati.org.tr",
            "Referer": "https://marketfiyati.org.tr/",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    clean_results = []
    seen = set()
    for product in payload.get("content") or []:
        title = product.get("title") or query
        brand = product.get("brand") or ""
        image_url = product.get("imageUrl") or ""
        for offer in product.get("productDepotInfoList") or []:
            price = parse_turkish_price(offer.get("price"))
            if price is None:
                continue

            source = offer.get("marketAdi") or "market"
            depot_name = offer.get("depotName") or source
            key = (source, depot_name, round(price, 2), title)
            if key in seen:
                continue
            seen.add(key)

            clean_results.append({
                "title": title,
                "brand": brand,
                "source": source,
                "store": source,
                "depot_name": depot_name,
                "price": float(price),
                "price_text": f"{price:.2f} TL",
                "unit_price": offer.get("unitPrice"),
                "image_url": image_url,
                "index_time": offer.get("indexTime"),
                "url": market_website_url(source, title or query),
                "link": market_website_url(source, title or query),
            })

    clean_results.sort(key=lambda x: x["price"])
    return clean_results


def price_query_variants(query: str) -> list[str]:
    clean = clean_product_query(query)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return []

    variants = [clean]
    no_size = re.sub(
        r"\b\d+([,.]\d+)?\s*(g|gr|gram|kg|ml|lt|l|adet)\b",
        " ",
        clean,
        flags=re.IGNORECASE
    )
    no_size = re.sub(r"\s+", " ", no_size).strip()
    if no_size and no_size not in variants:
        variants.append(no_size)

    words = no_size.split() if no_size else clean.split()
    for count in (5, 4, 3, 2):
        if len(words) >= count:
            candidate = " ".join(words[:count]).strip()
            if candidate and candidate not in variants:
                variants.append(candidate)

    filler = {
        "yarim", "yarım", "yagli", "yağlı", "az", "cok", "çok",
        "yogun", "yoğun", "kivamli", "kıvamlı", "esintisi",
        "dogal", "doğal", "klasik", "sade", "tam", "light"
    }
    core_words = [word for word in words if word.lower() not in filler]
    if len(core_words) >= 2:
        candidate = " ".join(core_words[:4]).strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    return variants[:7]


def _price_match_tokens(value: str) -> set[str]:
    normalized = (value or "").lower().translate(str.maketrans({
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    }))
    normalized = re.sub(
        r"\b\d+([,.]\d+)?\s*(g|gr|gram|kg|ml|lt|l|adet)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    ignored = {
        "ve", "ile", "icin", "urun", "yeni", "paket", "ekonomik",
    }
    return {
        token
        for token in re.sub(r"\s+", " ", normalized).strip().split()
        if len(token) >= 2 and token not in ignored
    }


def _price_result_score(query: str, result: dict) -> float:
    query_tokens = _price_match_tokens(query)
    title_tokens = _price_match_tokens(
        f"{result.get('brand', '')} {result.get('title', '')}"
    )
    if not query_tokens or not title_tokens:
        return 0.0
    overlap = query_tokens & title_tokens
    score = len(overlap) / len(query_tokens)
    first_token = re.sub(r"[^a-z0-9]", "", query.lower().translate(str.maketrans({
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    })).split()[0]) if query.strip() else ""
    if first_token and first_token in title_tokens:
        score += 0.25

    def amounts(value: str) -> set[int]:
        found = set()
        normalized = (value or "").lower().replace(",", ".")
        for number, unit in re.findall(
            r"(\d+(?:\.\d+)?)\s*(kg|g|gr|gram|lt|l|ml)\b",
            normalized,
        ):
            amount = float(number)
            if unit == "kg":
                amount *= 1000
            elif unit in {"lt", "l"}:
                amount *= 1000
            found.add(round(amount))
        return found

    query_amounts = amounts(query)
    title_amounts = amounts(str(result.get("title") or ""))
    if query_amounts and title_amounts:
        if query_amounts & title_amounts:
            score += 0.60
        else:
            score -= 0.60
    return score


def marketfiyati_search_fallback(query: str) -> tuple[list[dict], str]:
    variants = price_query_variants(query)
    best_by_store: dict[str, tuple[float, dict, str]] = {}

    for variant in variants:
        for result in marketfiyati_search(variant):
            score = _price_result_score(query, result)
            if score < 0.30:
                continue

            store = str(result.get("store") or result.get("source") or "").strip()
            if not store:
                continue

            current = best_by_store.get(store.lower())
            candidate_key = (score, -float(result.get("price") or 0))
            current_key = (
                (current[0], -float(current[1].get("price") or 0))
                if current
                else None
            )
            if current_key is None or candidate_key > current_key:
                best_by_store[store.lower()] = (score, result, variant)

    merged = [entry[1] for entry in best_by_store.values()]
    merged.sort(key=lambda item: float(item.get("price") or 0))
    for index, item in enumerate(merged):
        item["best"] = index == 0

    used_query = variants[0] if variants else query
    if best_by_store:
        used_query = max(best_by_store.values(), key=lambda entry: entry[0])[2]
    return merged[:8], used_query


def market_website_url(source: str, query: str) -> str:
    market = (source or "").lower().strip()
    q = urllib.parse.quote(query or "")
    if market == "migros":
        return f"https://www.migros.com.tr/arama?q={q}"
    if market == "a101":
        return f"https://www.a101.com.tr/arama/?q={q}"
    if market == "bim":
        return "https://www.bim.com.tr/"
    if market == "sok":
        return f"https://www.sokmarket.com.tr/arama?q={q}"
    if market == "carrefour":
        return f"https://www.carrefoursa.com/arama?text={q}"
    if market == "tarim_kredi":
        return "https://www.tarimkredikooperatifmarket.com.tr/"
    return f"https://www.google.com/search?q={urllib.parse.quote((source or 'market') + ' ' + (query or ''))}"


def build_price_message(product_name: str, query: str, results: list[dict]) -> dict:
    if not results:
        return {
            "title": "ğŸ’° Fiyat Bilgisi Bulunamadı",
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

    if saving_percent >= 10:
        risk = "low"
        price_status = "good"
        title = "ğŸŸ¢ Uygun Fiyat"
        comment = "Bulunan en düşük fiyat piyasa ortalamasının altında görünüyor."
    else:
        risk = "medium"
        price_status = "normal"
        title = "ğŸŸ¡ Benzer Fiyatlar"
        comment = "Bulunan mağaza fiyatları birbirine yakın görünüyor."

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
async def analyze_price(
    data: PriceRequest,
    _user: dict = Depends(require_price_right),
):
    detected = await detect_product_for_price(data)
    query = detected.get("query", "").strip()
    product_name = detected.get("product_name", query)

    if len(query) < 3:
        return {
            "title": "ğŸ’° Ürün Net Algılanamadı",
            "message": (
                "Fiyat karşılaştırması için ürün adı, marka veya gramaj net algılanamadı. "
                "Ürünün ön yüzünü, barkodunu veya fiyat etiketini daha net göstererek tekrar deneyin."
            ),
            "risk": "unknown",
            "query": query,
            "prices": []
        }

    try:
        results, used_query = marketfiyati_search_fallback(query)
        output = build_price_message(product_name, query, results)
        output["query"] = used_query
        output["confidence"] = detected.get("confidence", "medium")
        return output

    except Exception:
        return {
            "title": "ğŸ’° Fiyat Analizi Tamamlanamadı",
            "message": (
                "Fiyat karşılaştırması sırasında bağlantı veya API tarafında sorun oluştu. "
                "Market Fiyatı verisine ulaşılamadı. Biraz sonra tekrar deneyin."
            ),
            "risk": "unknown",
            "query": query,
            "prices": []
        }




# Besin tarafı: içerik analizi gibi güçlü, JSON tabanlı ve panel dostu çıktı üretir.

import json

from fastapi import APIRouter, Depends



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
    title = parsed.get("title") or "ğŸŸ¡ Besin Analizi"

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
        "product_name": product_name or "Gıda analizi",
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
async def analyze_nutrition(
    data: NutritionRequest,
    _user: dict = Depends(require_nutrition_right),
):
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
                "title": "ğŸŸ¡ Besin Analizi",
                "message": result_text,
                "risk": "medium",
                "score": 50,
                "nutrition": {},
                "alerts": ["Model yapılandırılmış JSON döndürmedi; sonuç tahmini olarak gösterildi."]
            })

        return normalize_nutrition_payload(parsed)

    except Exception:
        return normalize_nutrition_payload({
            "title": "ğŸŸ¡ Besin Analizi Tamamlanamadı",
            "message": "Besin analizi şu anda tamamlanamadı. Lütfen biraz sonra tekrar deneyin.",
            "risk": "unknown",
            "score": 0,
            "nutrition": {},
            "alerts": ["Bağlantı veya analiz sırasında sorun oluştu."]
        })

@app.get("/")
def root():
    return {"status": "ok", "service": "icinde-ne-var-backend"}
