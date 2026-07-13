"""Temizlik ürünleri için etiket-temelli güvenlik kataloğu.

Risk, ürünün etikette belirtilen konsantrasyonu ve kullanım talimatıyla birlikte
değerlendirilmelidir. Bu katalog gıdalardaki ADI yaklaşımını kullanmaz.
"""

CLEANING_SUBSTANCES = {
    "sodium hydroxide": {
        "domain": "cleaning",
        "risk": "high",
        "name": "Sodyum hidroksit",
        "purpose": "Yağ ve ağır kirleri çözmek veya pH düzenlemek için kullanılır.",
        "effect": "Konsantrasyona bağlı olarak korozif olabilir; cilt ve gözde ciddi yanık oluşturabilir.",
        "hazards": ["corrosive", "eye_damage", "skin_burn"],
    },
    "sodium hypochlorite": {
        "domain": "cleaning",
        "risk": "high",
        "name": "Sodyum hipoklorit / Aktif klor",
        "purpose": "Ağartma ve dezenfeksiyon amacıyla kullanılır.",
        "effect": "Cildi, gözü ve solunum yollarını tahriş edebilir. Asit veya amonyakla karıştırılmamalıdır.",
        "hazards": ["irritant", "toxic_mixture"],
        "never_mix_with": ["acid", "ammonia"],
    },
    "ammonia": {
        "domain": "cleaning",
        "risk": "high",
        "name": "Amonyak",
        "purpose": "Yağ ve kir çözmek için kullanılır.",
        "effect": "Buharı gözleri ve solunum yollarını tahriş edebilir. Klorlu ürünlerle karıştırılmamalıdır.",
        "hazards": ["respiratory_irritant", "toxic_mixture"],
        "never_mix_with": ["chlorine_bleach"],
    },
    "hydrochloric acid": {
        "domain": "cleaning",
        "risk": "high",
        "name": "Hidroklorik asit",
        "purpose": "Kireç, pas ve mineral kalıntılarını çözmek için kullanılır.",
        "effect": "Koroziftir. Klorlu ürünlerle karışması tehlikeli gaz açığa çıkarabilir.",
        "hazards": ["corrosive", "toxic_mixture"],
        "never_mix_with": ["chlorine_bleach"],
    },
    "benzalkonium chloride": {
        "domain": "cleaning",
        "risk": "high",
        "name": "Benzalkonyum klorür",
        "purpose": "Dezenfektan ve antimikrobiyal yüzey aktif madde olarak kullanılır.",
        "effect": "Konsantrasyona bağlı olarak ciltte, gözde ve solunum yollarında tahrişe yol açabilir.",
        "hazards": ["skin_irritant", "eye_damage"],
    },
    "nonionic surfactant": {
        "domain": "cleaning",
        "risk": "medium",
        "name": "Noniyonik yüzey aktif madde",
        "purpose": "Yağ ve kirin yüzeyden ayrılmasına yardımcı olur.",
        "effect": "Ürün yoğunluğuna göre cilt ve göz tahrişine neden olabilir.",
        "hazards": ["skin_irritant", "eye_irritant"],
    },
    "anionic surfactant": {
        "domain": "cleaning",
        "risk": "medium",
        "name": "Anyonik yüzey aktif madde",
        "purpose": "Temizleme ve köpürme etkisi sağlar.",
        "effect": "Hassas ciltlerde kuruluk veya tahriş oluşturabilir; gözle temastan kaçınılmalıdır.",
        "hazards": ["skin_irritant", "eye_irritant"],
    },
    "hydrogen peroxide": {
        "domain": "cleaning",
        "risk": "medium",
        "name": "Hidrojen peroksit",
        "purpose": "Ağartma, leke çıkarma ve oksitleyici temizlik için kullanılır.",
        "effect": "Risk konsantrasyona bağlıdır; cilt ve göz tahrişine neden olabilir.",
        "hazards": ["oxidizer", "eye_irritant"],
    },
}

CLEANING_ALIASES = {
    "sodyum hidroksit": "sodium hydroxide",
    "kostik soda": "sodium hydroxide",
    "sodyum hipoklorit": "sodium hypochlorite",
    "aktif klor": "sodium hypochlorite",
    "çamaşır suyu": "sodium hypochlorite",
    "amonyak": "ammonia",
    "hidroklorik asit": "hydrochloric acid",
    "tuz ruhu": "hydrochloric acid",
    "benzalkonyum klorür": "benzalkonium chloride",
    "noniyonik yüzey aktif madde": "nonionic surfactant",
    "noniyonik aktif madde": "nonionic surfactant",
    "anyonik yüzey aktif madde": "anionic surfactant",
    "hidrojen peroksit": "hydrogen peroxide",
}
