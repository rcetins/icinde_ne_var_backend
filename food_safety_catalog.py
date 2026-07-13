"""WHO/JECFA-oriented food ingredient catalogue used by the backend.

The traffic light is an information layer, not a diagnosis:
- low: no numerical ADI is normally required, or no special concern at permitted use;
- medium: intake is quantity-dependent, has an ADI, or needs a sensitivity warning;
- high: clear avoid case such as industrial trans fat.

An ingredient-list photo cannot establish whether an ADI was exceeded because the
concentration, portion, body weight and total daily exposure are not known.
"""

import re

JECFA_DATABASE = (
    "https://apps.who.int/food-additives-contaminants-jecfa-database/"
)
WHO_SUGAR_GUIDELINE = (
    "https://www.who.int/publications-detail-redirect/WHO-NMH-NHD-15.3"
)
WHO_TRANS_FAT = "https://www.who.int/news-room/fact-sheets/detail/trans-fat/"
WHO_NSS_GUIDELINE = "https://www.who.int/publications/i/item/9789240073616"


def _item(name, risk, purpose, effect, e_codes=(), adi=""):
    return {
        "name": name,
        "risk": risk,
        "purpose": purpose,
        "effect": effect,
        "e_codes": list(e_codes),
        "adi": adi,
        "source": "WHO/JECFA",
        "source_url": JECFA_DATABASE,
        "domain": "food",
    }


FOOD_ADDITIVES = {
    "citric acid": _item(
        "E330 - Sitrik asit", "low", "Asitlik düzenleyici ve aroma dengeleyicidir.",
        "JECFA, sitrik asit ve tuzları için sayısal ADI gerekli görmemiştir.", ("E330",), "Belirtilmemiş",
    ),
    "ascorbic acid": _item(
        "E300 - Askorbik asit (C vitamini)", "low", "Antioksidan olarak kullanılır.",
        "İzin verilen kullanımda belirgin bir katkı maddesi riski beklenmez.", ("E300",), "Belirtilmemiş",
    ),
    "sodium ascorbate": _item(
        "E301 - Sodyum askorbat", "low", "Antioksidan olarak kullanılır.",
        "Askorbik asidin sodyum tuzudur; izin verilen kullanımda düşük risklidir.", ("E301",), "Belirtilmemiş",
    ),
    "calcium ascorbate": _item(
        "E302 - Kalsiyum askorbat", "low", "Antioksidan olarak kullanılır.",
        "Askorbik asidin kalsiyum tuzudur; izin verilen kullanımda düşük risklidir.", ("E302",), "Belirtilmemiş",
    ),
    "lecithins": _item(
        "E322 - Lesitinler", "low", "Emülgatör olarak yağ ve suyun karışmasına yardım eder.",
        "Genel kullanımda düşük risklidir; soya veya yumurta kaynağı hassasiyet profilinde ayrıca gösterilmelidir.", ("E322",), "Belirtilmemiş",
    ),
    "sodium citrate": _item(
        "E331 - Sodyum sitrat", "low", "Asitlik düzenleyici ve stabilizatördür.",
        "JECFA sitrik asit ve sitratlar için önemli toksikolojik tehlike bildirmemiştir.", ("E331", "E331iii"), "Belirtilmemiş",
    ),
    "lactic acid": _item(
        "E270 - Laktik asit", "low", "Asitlik düzenleyici ve koruyucu destekleyicidir.",
        "İzin verilen kullanımda düşük riskli kabul edilir.", ("E270",), "Belirtilmemiş",
    ),
    "malic acid": _item(
        "E296 - Malik asit", "low", "Asitlik düzenleyici ve aroma dengeleyicidir.",
        "İzin verilen kullanımda düşük riskli kabul edilir.", ("E296",), "Belirtilmemiş",
    ),
    "beta carotene": _item(
        "E160a - Beta-karoten", "low", "Renklendirici ve provitamin A kaynağıdır.",
        "Gıdadaki izinli katkı kullanımı düşük riskli bilgi kategorisindedir.", ("E160a",), "Kullanıma göre",
    ),
    "pectin": _item(
        "E440 - Pektin", "low", "Jelleştirici ve kıvam artırıcıdır.",
        "Meyvelerde doğal olarak da bulunan bir liftir; izinli kullanımda düşük risklidir.", ("E440",), "Belirtilmemiş",
    ),
    "locust bean gum": _item(
        "E410 - Keçiboynuzu gamı", "low", "Kıvam artırıcı ve stabilizatördür.",
        "İzin verilen kullanımda düşük risklidir.", ("E410",), "Belirtilmemiş",
    ),
    "guar gum": _item(
        "E412 - Guar gam", "low", "Kıvam artırıcı ve stabilizatördür.",
        "İzin verilen kullanımda düşük risklidir; yüksek miktarlar sindirim hassasiyeti yapabilir.", ("E412",), "Belirtilmemiş",
    ),
    "xanthan gum": _item(
        "E415 - Ksantan gam", "low", "Kıvam artırıcı ve stabilizatördür.",
        "İzin verilen kullanımda düşük risklidir.", ("E415",), "Belirtilmemiş",
    ),
    "sodium carbonates": _item(
        "E500 - Sodyum karbonatlar", "low", "Kabartıcı ve asitlik düzenleyicidir.",
        "İzin verilen kullanımda düşük risklidir.", ("E500", "E500ii"), "Belirtilmemiş",
    ),
    "mono and diglycerides": _item(
        "E471 - Yağ asitlerinin mono ve digliseritleri", "low", "Emülgatördür.",
        "JECFA yaklaşımında izinli kullanım düşük risklidir; bitkisel veya hayvansal kaynak tercihi ayrıca gösterilmelidir.", ("E471",), "Belirtilmemiş",
    ),
    "silicon dioxide": _item(
        "E551 - Silisyum dioksit", "low", "Topaklanmayı önleyici olarak kullanılır.",
        "Gıdadaki izinli kullanım düşük riskli bilgi kategorisindedir.", ("E551",), "Belirtilmemiş",
    ),
    "sorbic acid": _item(
        "E200 - Sorbik asit", "medium", "Küf ve maya gelişimini azaltan koruyucudur.",
        "JECFA grup ADI değeri nedeniyle toplam günlük maruziyet miktara bağlıdır.", ("E200",), "0-25 mg/kg vücut ağırlığı",
    ),
    "sodium sorbate": _item(
        "E201 - Sodyum sorbat", "medium", "Koruyucudur.",
        "Sorbik asit ve sorbatlar için toplam günlük maruziyet miktara bağlıdır.", ("E201",), "0-25 mg/kg vücut ağırlığı",
    ),
    "potassium sorbate": _item(
        "E202 - Potasyum sorbat", "medium", "Küf ve maya gelişimini azaltan koruyucudur.",
        "İzinli düzeylerde kullanılabilir; hassasiyet ve toplam günlük sorbat alımı açısından bilgi verilmelidir.", ("E202",), "0-25 mg/kg vücut ağırlığı",
    ),
    "calcium sorbate": _item(
        "E203 - Kalsiyum sorbat", "medium", "Koruyucudur.",
        "Sorbik asit ve sorbatlar için toplam günlük maruziyet miktara bağlıdır.", ("E203",), "0-25 mg/kg vücut ağırlığı",
    ),
    "benzoic acid": _item(
        "E210 - Benzoik asit", "medium", "Koruyucudur.",
        "JECFA grup ADI değeri nedeniyle toplam günlük benzoat alımı miktara bağlıdır.", ("E210",), "0-20 mg/kg vücut ağırlığı",
    ),
    "sodium benzoate": _item(
        "E211 - Sodyum benzoat", "medium", "Koruyucudur.",
        "JECFA grup ADI değeri nedeniyle toplam günlük benzoat alımı miktara bağlıdır.", ("E211",), "0-20 mg/kg vücut ağırlığı",
    ),
    "potassium benzoate": _item(
        "E212 - Potasyum benzoat", "medium", "Koruyucudur.",
        "JECFA grup ADI değeri nedeniyle toplam günlük benzoat alımı miktara bağlıdır.", ("E212",), "0-20 mg/kg vücut ağırlığı",
    ),
    "calcium benzoate": _item(
        "E213 - Kalsiyum benzoat", "medium", "Koruyucudur.",
        "JECFA grup ADI değeri nedeniyle toplam günlük benzoat alımı miktara bağlıdır.", ("E213",), "0-20 mg/kg vücut ağırlığı",
    ),
    "sulfur dioxide and sulfites": _item(
        "E220-E228 - Sülfitler", "medium", "Koruyucu ve antioksidan olarak kullanılır.",
        "Astım veya sülfit hassasiyeti olanlarda özel uyarı gerekir; toplam maruziyet miktara bağlıdır.", tuple(f"E{n}" for n in range(220, 229)), "0-0,7 mg/kg (SO2 olarak)",
    ),
    "sodium nitrite": _item(
        "E250 - Sodyum nitrit", "medium", "İşlenmiş etlerde koruyucu ve renk sabitleyicidir.",
        "JECFA ADI düşüktür; özellikle işlenmiş et tüketim sıklığı ve bebek/çocuk profili açısından güçlü uyarı verilmelidir.", ("E250",), "0-0,07 mg/kg (nitrit iyonu olarak)",
    ),
    "potassium nitrite": _item(
        "E249 - Potasyum nitrit", "medium", "Koruyucu ve renk sabitleyicidir.",
        "Nitritlerin toplam günlük alımı ve işlenmiş et tüketim sıklığı önemlidir.", ("E249",), "0-0,07 mg/kg (nitrit iyonu olarak)",
    ),
    "sodium nitrate": _item(
        "E251 - Sodyum nitrat", "medium", "Koruyucu ve renk sabitleyicidir.",
        "JECFA ADI değeri nedeniyle toplam günlük nitrat alımı miktara bağlıdır.", ("E251",), "0-3,7 mg/kg (nitrat iyonu olarak)",
    ),
    "potassium nitrate": _item(
        "E252 - Potasyum nitrat", "medium", "Koruyucu ve renk sabitleyicidir.",
        "JECFA ADI değeri nedeniyle toplam günlük nitrat alımı miktara bağlıdır.", ("E252",), "0-3,7 mg/kg (nitrat iyonu olarak)",
    ),
    "phosphates": _item(
        "E338-E341 / E450-E452 - Fosfatlar", "medium", "Asitlik, kıvam ve nem düzenleme için kullanılır.",
        "Toplam fosfor alımı ürün miktarı ve beslenme düzeniyle birlikte değerlendirilmelidir.", ("E338", "E339", "E340", "E341", "E450", "E451", "E452"), "70 mg/kg (fosfor olarak grup MTDI)",
    ),
    "carrageenan": _item(
        "E407 - Karragenan", "medium", "Kıvam artırıcı ve stabilizatördür.",
        "Genel gıda kullanımında izinlidir; bebek ürünleri ve sindirim hassasiyeti ayrıca değerlendirilmelidir.", ("E407",), "Belirtilmemiş",
    ),
    "glycerol esters of wood rosin": _item(
        "E445 - Ağaç reçinesinin gliserol esterleri", "medium", "İçeceklerde yoğunluk ve aroma stabilizasyonu sağlar.",
        "JECFA ADI değeri nedeniyle toplam maruziyet miktara bağlıdır.", ("E445",), "0-25 mg/kg vücut ağırlığı",
    ),
    "bha": _item(
        "E320 - BHA", "medium", "Yağlarda oksidasyonu geciktiren antioksidandır.",
        "JECFA ADI değeri nedeniyle sık tüketilen ürünlerden toplam alım değerlendirilmelidir.", ("E320",), "0-0,5 mg/kg vücut ağırlığı",
    ),
    "bht": _item(
        "E321 - BHT", "medium", "Yağlarda oksidasyonu geciktiren antioksidandır.",
        "JECFA ADI değeri nedeniyle sık tüketilen ürünlerden toplam alım değerlendirilmelidir.", ("E321",), "0-0,3 mg/kg vücut ağırlığı",
    ),
    "acesulfame k": _item(
        "E950 - Asesülfam K", "medium", "Kalorisiz tatlandırıcıdır.",
        "JECFA ADI içinde kullanılabilir; WHO kilo kontrolü için şekersiz tatlandırıcılara dayanılmamasını önerir.", ("E950",), "0-15 mg/kg vücut ağırlığı",
    ),
    "aspartame": _item(
        "E951 - Aspartam", "medium", "Kalorisiz tatlandırıcıdır.",
        "JECFA ADI değerini korur; fenilketonürisi olanlar için uygun değildir ve özel uyarı gerekir.", ("E951",), "0-40 mg/kg vücut ağırlığı",
    ),
    "cyclamates": _item(
        "E952 - Siklamatlar", "medium", "Kalorisiz tatlandırıcıdır.",
        "Toplam günlük tatlandırıcı alımı ve JECFA ADI değeri dikkate alınmalıdır.", ("E952",), "0-11 mg/kg vücut ağırlığı",
    ),
    "saccharins": _item(
        "E954 - Sakarinler", "medium", "Kalorisiz tatlandırıcıdır.",
        "Toplam günlük tatlandırıcı alımı ve JECFA ADI değeri dikkate alınmalıdır.", ("E954",), "0-5 mg/kg vücut ağırlığı",
    ),
    "sucralose": _item(
        "E955 - Sukraloz", "medium", "Kalorisiz tatlandırıcıdır.",
        "Toplam günlük tatlandırıcı alımı ve JECFA ADI değeri dikkate alınmalıdır.", ("E955",), "0-15 mg/kg vücut ağırlığı",
    ),
    "steviol glycosides": _item(
        "E960 - Steviol glikozitleri", "medium", "Yoğun tatlandırıcıdır.",
        "Toplam günlük tatlandırıcı alımı ve JECFA ADI değeri dikkate alınmalıdır.", ("E960",), "0-4 mg/kg (steviol olarak)",
    ),
    "monosodium glutamate": _item(
        "E621 - Monosodyum glutamat (MSG)", "medium", "Lezzet artırıcıdır.",
        "JECFA sayısal ADI gerekli görmemiştir; ürünün toplam sodyumu ve kişisel hassasiyet ayrı değerlendirilmelidir.", ("E621",), "Belirtilmemiş",
    ),
    "titanium dioxide": _item(
        "E171 - Titanyum dioksit", "medium", "Beyaz renklendiricidir.",
        "JECFA 2023 değerlendirmesinde ADI'yi belirtilmemiş olarak korumuştur; bölgesel mevzuat durumu ayrıca gösterilmelidir.", ("E171",), "Belirtilmemiş",
    ),
    "glucose syrup": _item(
        "Glikoz şurubu", "medium", "Tatlandırma ve kıvam için kullanılır.",
        "WHO serbest şeker hedefleri açısından miktar ve tüketim sıklığı önemlidir; yalnız varlığı kırmızı karar için yeterli değildir.", (), "WHO: serbest şeker <%10 enerji, tercihen <%5",
    ),
    "fructose syrup": _item(
        "Fruktoz şurubu", "medium", "Tatlandırma için kullanılır.",
        "WHO serbest şeker hedefleri açısından miktar ve tüketim sıklığı önemlidir; yalnız varlığı kırmızı karar için yeterli değildir.", (), "WHO: serbest şeker <%10 enerji, tercihen <%5",
    ),
    "corn syrup": _item(
        "Mısır şurubu / HFCS", "medium", "Tatlandırma için kullanılır.",
        "WHO serbest şeker hedefleri açısından miktar ve tüketim sıklığı önemlidir; yalnız varlığı kırmızı karar için yeterli değildir.", (), "WHO: serbest şeker <%10 enerji, tercihen <%5",
    ),
    "sugar": _item(
        "Şeker", "medium", "Tat vermek için kullanılır.",
        "Toplam serbest şeker miktarı ve tüketim sıklığı önemlidir; yalnız etikette bulunması kırmızı karar için yeterli değildir.", (), "WHO: serbest şeker <%10 enerji, tercihen <%5",
    ),
    "fructose": _item(
        "Fruktoz", "medium", "Tatlandırıcı şeker olarak kullanılır.",
        "Toplam serbest şeker miktarı ve tüketim sıklığıyla birlikte değerlendirilmelidir.", (), "Miktara bağlı",
    ),
    "palm oil": _item(
        "Palm yağı", "medium", "Yağ, kıvam ve raf dayanımı sağlar.",
        "Ürünün toplam doymuş yağ miktarı ve tüketim sıklığıyla birlikte değerlendirilmelidir.", (), "Miktara bağlı",
    ),
    "modified starch": _item(
        "Modifiye nişasta", "medium", "Kıvam ve yapı düzenleyici olarak kullanılır.",
        "Tek başına yüksek risk göstermez; ürünün genel işlenmişlik profiliyle birlikte değerlendirilir.", (), "Belirtilmemiş",
    ),
    "flavouring": _item(
        "Aroma verici", "medium", "Ürüne tat veya koku profili kazandırır.",
        "Genellikle düşük miktarda kullanılır; hassasiyet ve içerik şeffaflığı açısından değerlendirilebilir.", (), "Miktara bağlı",
    ),
    "hydrogenated oil": _item(
        "Hidrojene yağ", "medium", "Yağın yapı ve raf ömrünü değiştirmek için kullanılır.",
        "Tam hidrojene yağ otomatik olarak trans yağ değildir; etikette 'kısmen hidrojene' veya trans yağ varsa kırmızı değerlendirilir.", (), "Miktara bağlı",
    ),
    "industrial trans fat": _item(
        "Endüstriyel trans yağ / kısmen hidrojene yağ", "high", "Katı yağ yapısı ve raf ömrü için oluşabilir.",
        "WHO endüstriyel trans yağlardan kaçınılmasını ve toplam trans yağın enerjinin %1'inden az tutulmasını önerir.", (), "WHO: <%1 toplam enerji",
    ),
}


FOOD_ALIASES = {
    "sitrik asit": "citric acid", "citric acid": "citric acid",
    "askorbik asit": "ascorbic acid", "ascorbic acid": "ascorbic acid",
    "sodyum askorbat": "sodium ascorbate", "kalsiyum askorbat": "calcium ascorbate",
    "lesitin": "lecithins", "lecithin": "lecithins", "lecithins": "lecithins",
    "sodyum sitrat": "sodium citrate", "sodium citrate": "sodium citrate",
    "laktik asit": "lactic acid", "lactic acid": "lactic acid",
    "malik asit": "malic acid", "malic acid": "malic acid",
    "beta-karoten": "beta carotene", "beta carotene": "beta carotene",
    "pektin": "pectin", "pektinler": "pectin", "pectin": "pectin",
    "keçiboynuzu gamı": "locust bean gum", "locust bean gum": "locust bean gum",
    "guar gam": "guar gum", "guar gum": "guar gum",
    "ksantan gam": "xanthan gum", "xanthan gum": "xanthan gum",
    "sodyum karbonat": "sodium carbonates", "sodyum bikarbonat": "sodium carbonates",
    "sodium carbonate": "sodium carbonates", "sodium bicarbonate": "sodium carbonates",
    "mono ve digliseritler": "mono and diglycerides", "mono- ve digliseritler": "mono and diglycerides",
    "mono and diglycerides": "mono and diglycerides", "silisyum dioksit": "silicon dioxide",
    "silicon dioxide": "silicon dioxide", "sorbik asit": "sorbic acid",
    "sorbic acid": "sorbic acid", "sodyum sorbat": "sodium sorbate",
    "potasyum sorbat": "potassium sorbate", "potassium sorbate": "potassium sorbate",
    "kalsiyum sorbat": "calcium sorbate", "benzoik asit": "benzoic acid",
    "sodyum benzoat": "sodium benzoate", "sodium benzoate": "sodium benzoate",
    "potasyum benzoat": "potassium benzoate", "kalsiyum benzoat": "calcium benzoate",
    "sülfit": "sulfur dioxide and sulfites", "sülfitler": "sulfur dioxide and sulfites",
    "sulfite": "sulfur dioxide and sulfites", "sulfites": "sulfur dioxide and sulfites",
    "sodyum nitrit": "sodium nitrite", "nitrit": "sodium nitrite", "sodium nitrite": "sodium nitrite",
    "potasyum nitrit": "potassium nitrite", "sodyum nitrat": "sodium nitrate",
    "potasyum nitrat": "potassium nitrate", "fosfat": "phosphates", "fosfatlar": "phosphates",
    "phosphate": "phosphates", "phosphates": "phosphates", "karragenan": "carrageenan",
    "carrageenan": "carrageenan", "ağaç reçinesinin gliserol esterleri": "glycerol esters of wood rosin",
    "glycerol esters of wood rosin": "glycerol esters of wood rosin",
    "asesülfam k": "acesulfame k", "asesulfam k": "acesulfame k", "acesulfam": "acesulfame k",
    "acesulfame potassium": "acesulfame k", "acesulfame k": "acesulfame k",
    "aspartam": "aspartame", "aspartame": "aspartame", "siklamat": "cyclamates",
    "cyclamate": "cyclamates", "sakarin": "saccharins", "saccharin": "saccharins",
    "sukraloz": "sucralose", "sucralose": "sucralose", "steviol glikozitleri": "steviol glycosides",
    "steviol glycosides": "steviol glycosides", "monosodyum glutamat": "monosodium glutamate",
    "monosodium glutamate": "monosodium glutamate", "msg": "monosodium glutamate",
    "titanyum dioksit": "titanium dioxide", "titanium dioxide": "titanium dioxide",
    "glikoz şurubu": "glucose syrup", "glikoz surubu": "glucose syrup", "glucose syrup": "glucose syrup",
    "fruktoz şurubu": "fructose syrup", "fruktoz surubu": "fructose syrup", "fructose syrup": "fructose syrup",
    "mısır şurubu": "corn syrup", "misir surubu": "corn syrup", "corn syrup": "corn syrup",
    "high fructose corn syrup": "corn syrup", "hfcs": "corn syrup",
    "şeker": "sugar", "seker": "sugar", "sugar": "sugar",
    "fruktoz": "fructose", "fructose": "fructose",
    "palm": "palm oil", "palm yağı": "palm oil", "palm oil": "palm oil",
    "modified food starch": "modified starch", "modified corn starch": "modified starch",
    "modifiye nişasta": "modified starch",
    "aroma": "flavouring", "natural flavor": "flavouring", "natural flavors": "flavouring",
    "hidrojene": "hydrogenated oil", "hydrogenated": "hydrogenated oil",
    "hidrojene yağ": "hydrogenated oil", "hydrogenated oil": "hydrogenated oil",
    "kısmen hidrojene": "industrial trans fat", "partially hydrogenated": "industrial trans fat",
    "trans yağ": "industrial trans fat", "trans fat": "industrial trans fat",
}

for key in ("glucose syrup", "fructose syrup", "corn syrup", "sugar"):
    FOOD_ADDITIVES[key]["source_url"] = WHO_SUGAR_GUIDELINE
for key in (
    "acesulfame k", "aspartame", "cyclamates", "saccharins",
    "sucralose", "steviol glycosides",
):
    FOOD_ADDITIVES[key]["guidance_url"] = WHO_NSS_GUIDELINE
FOOD_ADDITIVES["industrial trans fat"]["source_url"] = WHO_TRANS_FAT


for canonical, item in FOOD_ADDITIVES.items():
    FOOD_ALIASES.setdefault(canonical, canonical)
    for code in item.get("e_codes", []):
        normalized = code.lower()
        FOOD_ALIASES[normalized] = canonical
        if normalized.startswith("e"):
            number = normalized[1:]
            FOOD_ALIASES[f"e {number}"] = canonical
            FOOD_ALIASES[f"ins {number}"] = canonical


def normalized_food_risk(label: str, fallback: str = "medium") -> str:
    """Apply catalogue guardrails to an AI-provided ingredient risk."""
    lower = (label or "").lower()
    for alias in sorted(FOOD_ALIASES, key=len, reverse=True):
        if re.search(r"(?<![\w])" + re.escape(alias) + r"(?![\w])", lower):
            return FOOD_ADDITIVES[FOOD_ALIASES[alias]]["risk"]
    return fallback if fallback in {"low", "medium", "high", "unknown"} else "medium"


def unknown_e_codes(text: str) -> list[str]:
    """Return E/INS codes that are not yet covered by the local catalogue."""
    found = []
    seen = set()
    for match in re.finditer(r"(?<![\w])(?:e|ins)\s*([1-9]\d{1,3}[a-z]*)(?![\w])", (text or "").lower()):
        number = match.group(1)
        if f"e{number}" in FOOD_ALIASES:
            continue
        code = f"E{number.upper()}"
        if code not in seen:
            seen.add(code)
            found.append(code)
    return found
