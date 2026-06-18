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

    return extracted[:1800].strip()


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
    "acesulfame potassium": {
        "risk": "high",
        "name": "Acesulfame Potassium / Acesulfam K",
        "purpose": "Kalorisiz yapay tatlandırıcı olarak kullanılır.",
        "effect": "Sık tüketilen diyet ürünlerde toplam yapay tatlandırıcı alımı açısından dikkat gerektirir."
    },
    "acesulfame k": {
        "risk": "high",
        "name": "Acesulfame K / Acesulfam K",
        "purpose": "Kalorisiz yapay tatlandırıcı olarak kullanılır.",
        "effect": "Toplam yapay tatlandırıcı yükü açısından dikkatle değerlendirilmelidir."
    },
    "aspartame": {
        "risk": "high",
        "name": "Aspartame / Aspartam",
        "purpose": "Şekersiz veya düşük kalorili ürünlerde tatlandırıcı olarak kullanılır.",
        "effect": "Fenilketonüri hastaları için uygun değildir; hassas kişilerde ve sık tüketimde dikkat gerektirir."
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
    "high fructose corn syrup": {
        "risk": "high",
        "name": "High Fructose Corn Syrup",
        "purpose": "Tatlandırıcı şurup olarak kullanılır.",
        "effect": "Sık tüketimde şeker ve kalori yükünü artırabilir; özellikle içecek ve tatlı ürünlerde dikkat gerektirir."
    },
    "mısır şurubu": {
        "risk": "high",
        "name": "Mısır şurubu",
        "purpose": "Tatlandırma ve kıvam için kullanılır.",
        "effect": "Şeker ve kalori yükünü artırabilir; sık tüketimde dikkat gerektirir."
    },
    "corn syrup": {
        "risk": "high",
        "name": "Corn Syrup / Mısır şurubu",
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
    "fructose": {
        "risk": "medium",
        "name": "Fructose / Fruktoz",
        "purpose": "Tatlandırıcı olarak kullanılır.",
        "effect": "Sık tüketimde toplam şeker yüküne katkı sağlayabilir."
    },
    "sucralose": {
        "risk": "medium",
        "name": "Sucralose / Sukraloz",
        "purpose": "Kalorisiz yapay tatlandırıcı olarak kullanılır.",
        "effect": "Genel limitler içinde kullanılır; sık tüketimde toplam yapay tatlandırıcı alımı açısından dikkat edilebilir."
    },
    "potassium sorbate": {
        "risk": "medium",
        "name": "Potassium Sorbate / Potasyum sorbat",
        "purpose": "Küf ve maya gelişimini azaltmak için koruyucu olarak kullanılır.",
        "effect": "Genelde düşük miktarda kullanılır; hassas kişilerde dikkat gerektirebilir."
    },
    "potasyum sorbat": {
        "risk": "medium",
        "name": "Potasyum sorbat",
        "purpose": "Küf ve maya gelişimini azaltmak için koruyucu olarak kullanılır.",
        "effect": "Genelde düşük miktarda kullanılır; hassas kişilerde dikkat gerektirebilir."
    },
    "sorbic acid": {
        "risk": "medium",
        "name": "Sorbic Acid / Sorbik asit",
        "purpose": "Koruyucu olarak kullanılır.",
        "effect": "Hassas kişilerde dikkat gerektirebilir."
    },
    "sorbik asit": {
        "risk": "medium",
        "name": "Sorbik asit",
        "purpose": "Koruyucu olarak kullanılır.",
        "effect": "Hassas kişilerde dikkat gerektirebilir."
    },
    "modified food starch": {
        "risk": "medium",
        "name": "Modified Food Starch",
        "purpose": "Kıvam ve yapı düzenleyici olarak kullanılır.",
        "effect": "Genelde teknolojik katkıdır; yoğun işlenmiş ürünlerde içerik kalitesi açısından dikkat edilebilir."
    },
    "modified corn starch": {
        "risk": "medium",
        "name": "Modified Corn Starch",
        "purpose": "Kıvam ve yapı düzenleyici olarak kullanılır.",
        "effect": "Genelde teknolojik katkıdır; yoğun işlenmiş ürünlerde dikkat edilebilir."
    },
    "natural flavor": {
        "risk": "medium",
        "name": "Natural Flavor / Doğal aroma",
        "purpose": "Ürüne tat ve koku profili vermek için kullanılır.",
        "effect": "Genelde düşük miktarda kullanılır; içerik şeffaflığı açısından dikkat edilebilir."
    },
    "natural flavors": {
        "risk": "medium",
        "name": "Natural Flavor / Doğal aroma",
        "purpose": "Ürüne tat ve koku profili vermek için kullanılır.",
        "effect": "Genelde düşük miktarda kullanılır; içerik şeffaflığı açısından dikkat edilebilir."
    },
    "sodium citrate": {
        "risk": "medium",
        "name": "Sodium Citrate / Sodyum sitrat",
        "purpose": "Asitlik düzenleyici ve stabilizatör olarak kullanılır.",
        "effect": "Genelde teknolojik katkıdır; sodyum içeriği ve ürünün genel işlenmişliği ile birlikte değerlendirilir."
    },
    "malic acid": {
        "risk": "medium",
        "name": "Malic Acid / Malik asit",
        "purpose": "Asitlik düzenleyici olarak kullanılır.",
        "effect": "Genelde düşük miktarda kullanılır; hassas kişilerde dikkat edilebilir."
    },
    "non fat milk": {
        "risk": "low",
        "name": "Non fat milk / Yağsız süt",
        "purpose": "Süt bazlı ana bileşen olarak kullanılır.",
        "effect": "Süt alerjisi veya laktoz hassasiyeti olan kişiler için dikkat edilmelidir."
    },
    "milk": {
        "risk": "low",
        "name": "Milk / Süt",
        "purpose": "Süt bazlı ana bileşen olarak kullanılır.",
        "effect": "Süt alerjisi veya laktoz hassasiyeti olan kişiler için dikkat edilmelidir."
    },
    "water": {
        "risk": "low",
        "name": "Water / Su",
        "purpose": "Çözücü veya ana bileşen olarak kullanılır.",
        "effect": "Belirgin riskli katkı değildir."
    },
    "strawberries": {
        "risk": "low",
        "name": "Strawberries / Çilek",
        "purpose": "Meyve bileşeni olarak kullanılır.",
        "effect": "Genel olarak olumlu/nötr içeriktir; alerjisi olan kişiler dikkat etmelidir."
    },
    "strawberry": {
        "risk": "low",
        "name": "Strawberry / Çilek",
        "purpose": "Meyve bileşeni olarak kullanılır.",
        "effect": "Genel olarak olumlu/nötr içeriktir; alerjisi olan kişiler dikkat etmelidir."
    },
    "vitamin d3": {
        "risk": "low",
        "name": "Vitamin D3",
        "purpose": "Vitamin desteği için kullanılır.",
        "effect": "Belirgin riskli katkı değildir; miktar ve ürün bağlamı önemlidir."
    },
    "vitamin a palmitate": {
        "risk": "low",
        "name": "Vitamin A Palmitate",
        "purpose": "Vitamin A desteği için kullanılır.",
        "effect": "Palm yağı değildir; vitamin bileşiği olarak değerlendirilir."
    },
    "yogurt cultures": {
        "risk": "low",
        "name": "Yogurt cultures / Yoğurt kültürleri",
        "purpose": "Yoğurt kültürü olarak kullanılır.",
        "effect": "Belirgin riskli katkı değildir."
    },
    "l. acidophilus": {
        "risk": "low",
        "name": "L. acidophilus",
        "purpose": "Yoğurt/probiyotik kültür olarak kullanılır.",
        "effect": "Belirgin riskli katkı değildir."
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
    "sodyum hidroksit": {
        "risk": "high",
        "name": "Sodyum hidroksit",
        "purpose": "Yağ ve kirleri çözmek, ürünün pH seviyesini düzenlemek için kullanılır.",
        "effect": "Korozif olabilir; ciltte ve gözde ciddi tahriş veya yanık riski oluşturabilir. Etiket talimatlarına kesinlikle uyulmalıdır."
    },
    "sodium hydroxide": {
        "risk": "high",
        "name": "Sodyum hidroksit",
        "purpose": "Yağ ve kirleri çözmek, ürünün pH seviyesini düzenlemek için kullanılır.",
        "effect": "Korozif olabilir; ciltte ve gözde ciddi tahriş veya yanık riski oluşturabilir. Etiket talimatlarına kesinlikle uyulmalıdır."
    },
    "sodyum hipoklorit": {
        "risk": "high",
        "name": "Sodyum hipoklorit / Aktif klor",
        "purpose": "Ağartma, dezenfeksiyon ve mikrobiyal temizlik için kullanılır.",
        "effect": "Cilt, göz ve solunum yollarını tahriş edebilir. Asit veya amonyak içeren ürünlerle kesinlikle karıştırılmamalıdır."
    },
    "sodium hypochlorite": {
        "risk": "high",
        "name": "Sodyum hipoklorit / Aktif klor",
        "purpose": "Ağartma, dezenfeksiyon ve mikrobiyal temizlik için kullanılır.",
        "effect": "Cilt, göz ve solunum yollarını tahriş edebilir. Asit veya amonyak içeren ürünlerle kesinlikle karıştırılmamalıdır."
    },
    "aktif klor": {
        "risk": "high",
        "name": "Aktif klor",
        "purpose": "Ağartıcı ve dezenfektan etki sağlar.",
        "effect": "Tahriş edici gaz oluşturma riski nedeniyle asit ve amonyak içeren temizleyicilerle karıştırılmamalıdır."
    },
    "amonyak": {
        "risk": "high",
        "name": "Amonyak",
        "purpose": "Yağ ve kir çözme amacıyla bazı temizlik ürünlerinde kullanılır.",
        "effect": "Buharı gözleri ve solunum yollarını tahriş edebilir. Klorlu ürünlerle karıştırılması tehlikelidir."
    },
    "ammonia": {
        "risk": "high",
        "name": "Amonyak",
        "purpose": "Yağ ve kir çözme amacıyla bazı temizlik ürünlerinde kullanılır.",
        "effect": "Buharı gözleri ve solunum yollarını tahriş edebilir. Klorlu ürünlerle karıştırılması tehlikelidir."
    },
    "hidroklorik asit": {
        "risk": "high",
        "name": "Hidroklorik asit",
        "purpose": "Kireç, pas ve mineral kalıntılarını çözmek için kullanılır.",
        "effect": "Koroziftir; klorlu ürünlerle karıştırıldığında tehlikeli gaz açığa çıkarabilir."
    },
    "hydrochloric acid": {
        "risk": "high",
        "name": "Hidroklorik asit",
        "purpose": "Kireç, pas ve mineral kalıntılarını çözmek için kullanılır.",
        "effect": "Koroziftir; klorlu ürünlerle karıştırıldığında tehlikeli gaz açığa çıkarabilir."
    },
    "benzalkonyum klorür": {
        "risk": "high",
        "name": "Benzalkonyum klorür",
        "purpose": "Dezenfektan ve antimikrobiyal yüzey aktif madde olarak kullanılır.",
        "effect": "Yoğun temas ciltte, gözde ve solunum yollarında tahrişe neden olabilir."
    },
    "benzalkonium chloride": {
        "risk": "high",
        "name": "Benzalkonyum klorür",
        "purpose": "Dezenfektan ve antimikrobiyal yüzey aktif madde olarak kullanılır.",
        "effect": "Yoğun temas ciltte, gözde ve solunum yollarında tahrişe neden olabilir."
    },
    "noniyonik yüzey aktif madde": {
        "risk": "medium",
        "name": "Noniyonik yüzey aktif madde",
        "purpose": "Yağ ve kirin yüzeyden ayrılmasına yardımcı olur.",
        "effect": "Ürün yoğunluğuna göre cilt ve göz tahrişine neden olabilir; doğrudan temastan kaçınılmalıdır."
    },
    "nonionic surfactant": {
        "risk": "medium",
        "name": "Noniyonik yüzey aktif madde",
        "purpose": "Yağ ve kirin yüzeyden ayrılmasına yardımcı olur.",
        "effect": "Ürün yoğunluğuna göre cilt ve göz tahrişine neden olabilir; doğrudan temastan kaçınılmalıdır."
    },
    "anyonik yüzey aktif madde": {
        "risk": "medium",
        "name": "Anyonik yüzey aktif madde",
        "purpose": "Temizleme ve köpürme etkisi sağlar.",
        "effect": "Hassas ciltlerde kuruluk ve tahriş oluşturabilir; gözle temasından kaçınılmalıdır."
    },
    "anionic surfactant": {
        "risk": "medium",
        "name": "Anyonik yüzey aktif madde",
        "purpose": "Temizleme ve köpürme etkisi sağlar.",
        "effect": "Hassas ciltlerde kuruluk ve tahriş oluşturabilir; gözle temasından kaçınılmalıdır."
    },
    "hidrojen peroksit": {
        "risk": "medium",
        "name": "Hidrojen peroksit",
        "purpose": "Ağartma, leke çıkarma ve oksitleyici temizlik için kullanılır.",
        "effect": "Konsantrasyona bağlı olarak cilt ve göz tahrişine neden olabilir."
    },
    "hydrogen peroxide": {
        "risk": "medium",
        "name": "Hidrojen peroksit",
        "purpose": "Ağartma, leke çıkarma ve oksitleyici temizlik için kullanılır.",
        "effect": "Konsantrasyona bağlı olarak cilt ve göz tahrişine neden olabilir."
    },
}

TERM_ALIASES = {
    # Sweeteners
    "阿斯巴甜": "aspartame",
    "acésulfame potassium": "acesulfame potassium",
    "acésulfame k": "acesulfame k",
    "acesulfam-k": "acesulfame k",
    "acesulfam k": "acesulfame k",
    "安赛蜜": "acesulfame potassium",
    "乙酰磺胺酸钾": "acesulfame potassium",
    "sucralose": "sucralose",
    "三氯蔗糖": "sucralose",
    "fruktose": "fructose",
    "果糖": "fructose",

    # Preservatives and acidity regulators
    "kaliumsorbat": "potassium sorbate",
    "sorbate de potassium": "potassium sorbate",
    "山梨酸钾": "potassium sorbate",
    "sorbinsäure": "sorbic acid",
    "acide sorbique": "sorbic acid",
    "山梨酸": "sorbic acid",
    "natriumcitrat": "sodium citrate",
    "citrate de sodium": "sodium citrate",
    "柠檬酸钠": "sodium citrate",
    "apfelsäure": "malic acid",
    "acide malique": "malic acid",
    "苹果酸": "malic acid",

    # Starches, aromas and processing aids
    "modifizierte stärke": "modified food starch",
    "amidon modifié": "modified food starch",
    "变性淀粉": "modified food starch",
    "modifizierte maisstärke": "modified corn starch",
    "amidon de maïs modifié": "modified corn starch",
    "变性玉米淀粉": "modified corn starch",
    "natürliches aroma": "natural flavor",
    "natürliche aromen": "natural flavor",
    "arôme naturel": "natural flavor",
    "arômes naturels": "natural flavors",
    "天然香料": "natural flavor",

    # Higher attention additives
    "mononatriumglutamat": "monosodyum glutamat",
    "glutamate monosodique": "monosodyum glutamat",
    "谷氨酸钠": "monosodyum glutamat",
    "natriumnitrit": "sodyum nitrit",
    "nitrite de sodium": "sodyum nitrit",
    "亚硝酸钠": "sodyum nitrit",
    "nitrit": "nitrit",
    "nitrite": "nitrit",
    "亚硝酸盐": "nitrit",
    "titandioxid": "titanyum dioksit",
    "dioxyde de titane": "titanyum dioksit",
    "二氧化钛": "titanyum dioksit",
    "palmöl": "palm",
    "huile de palme": "palm",
    "棕榈油": "palm",

    # Cosmetic labels
    "parfum": "fragrance",
    "duftstoff": "fragrance",
    "香精": "fragrance",
    "苯氧乙醇": "phenoxyethanol",
    "甲基异噻唑啉酮": "methylisothiazolinone",
    "三氯生": "triclosan",
}

for alias, canonical in TERM_ALIASES.items():
    if canonical in TERM_INFO:
        TERM_INFO.setdefault(alias, TERM_INFO[canonical])


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
        shown = found[:24]

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


def is_instruction_or_warning_text(value: str) -> bool:
    lower = normalize_text(value).lower().translate(str.maketrans({
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    }))
    if not lower:
        return True

    instruction_phrases = [
        "kisinin bilinci", "bilinci acik", "ilk yardim",
        "goz ile temas", "gozle temas", "derhal", "doktor",
        "zehir danisma", "iyice karistir", "kullanmadan once",
        "kullanim talimat", "durulayin", "cocuklarin ulasamayacagi",
        "eldiven kullan", "yutulmasi halinde", "paslanmaz celik",
        "uygun degildir", "sadece kullanim",
    ]
    if any(phrase in lower for phrase in instruction_phrases):
        return True

    instruction_verbs = [
        "uygulayin", "bekletin", "temizleyin", "karistirin",
        "kullaniniz", "saklayiniz", "basvurun", "cikarin",
    ]
    return any(verb in lower for verb in instruction_verbs)


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
            key = name.lower()
            if key in seen:
                continue
            merged.append(item)
            seen.add(key)

    combined_text = "\n".join([str(text or "") for text in texts])
    for item in find_terms(combined_text):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            for existing in merged:
                if str(existing.get("name") or "").strip().lower() != key:
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

    return merged[:30]


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
async def analyze_content(data: ContentRequest):
    raw_text = normalize_text(data.text)
    content_text = extract_relevant_content(raw_text)
    quality = ocr_quality(content_text)
    has_image = bool((data.image or "").strip())
    requested_language = response_language_code(data.language)
    response_language = response_language_name(data.language)

    fallback = local_content_analysis(content_text, quality)

    # Görsel yoksa ve OCR okunamadıysa risk rengi üretmek yerine unknown döndür.
    if requested_language == "tr" and fallback["risk"] == "unknown" and not has_image:
        return fallback

    if (
        requested_language == "tr"
        and fallback.get("risk") != "unknown"
        and quality.get("can_be_low")
        and len(fallback.get("detected_items", [])) >= 5
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
  "title": "🔴/🟡/🟢/⚠️ kısa başlık",
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
            max_tokens=1100
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
            "title": ai_result.get("title") or risk_title(final_risk),
            "message": ai_result.get("message") or fallback["message"],
            "risk": final_risk,
            "read_text": read_text,
            "detected_items": detected_items
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
        results, used_query = marketfiyati_search_fallback(query)
        output = build_price_message(product_name, query, results)
        output["query"] = used_query
        output["confidence"] = detected.get("confidence", "medium")
        return output

    except Exception as e:
        return {
            "title": "💰 Fiyat Analizi Tamamlanamadı",
            "message": (
                "Fiyat karşılaştırması sırasında bağlantı veya API tarafında sorun oluştu. "
                "Market Fiyatı verisine ulaşılamadı. Biraz sonra tekrar deneyin."
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
