"""
generate_pricing_dataset.py
-----------------------------
Generates a synthetic but realistic dataset of "what medical procedures/
items typically cost" across different hospitals, cities and categories.
This is the training data for the Fair Price Prediction model.

In a real deployment you would replace this with actual market-rate data
(e.g. CGHS rate lists, insurer-published tariffs, or your own hospital's
billing history). The generation logic below encodes realistic pricing
relationships (category baseline price, city-tier multiplier, hospital-type
multiplier, plus noise) so a model trained on it learns sensible patterns.
"""

import numpy as np
import pandas as pd

RANDOM_STATE = 42
np.random.seed(RANDOM_STATE)

# Baseline price (Rs.) for each category — what a mid-tier hospital in a
# tier-2 city, private, would typically charge.
CATEGORY_BASE_PRICE = {
    "room_rent": 3000,       # per day
    "procedure": 35000,      # per procedure
    "medicine": 150,         # per line item
    "diagnostic": 2000,      # per test/scan
    "nursing": 1200,         # per day
    "consultation": 600,     # per visit
}

CITY_TIER_MULTIPLIER = {
    "metro": 1.35,      # Mumbai, Delhi, Bangalore, Chennai...
    "tier2": 1.0,        # Coimbatore, Nagpur, Kochi...
    "tier3": 0.75,       # smaller towns
}

HOSPITAL_TYPE_MULTIPLIER = {
    "government": 0.35,
    "private": 1.0,
    "multispeciality": 1.25,
    "premium": 1.8,
}


def generate_pricing_dataset(n_samples: int = 6000) -> pd.DataFrame:
    categories = list(CATEGORY_BASE_PRICE.keys())
    city_tiers = list(CITY_TIER_MULTIPLIER.keys())
    hospital_types = list(HOSPITAL_TYPE_MULTIPLIER.keys())

    # categories billed "per unit" where quantity meaningfully scales the
    # total (room_rent/nursing = per day, medicine/diagnostic = per item);
    # procedure and consultation are normally billed as a single flat fee
    PER_UNIT_CATEGORIES = {"room_rent", "nursing", "medicine", "diagnostic"}

    rows = []
    for _ in range(n_samples):
        category = np.random.choice(categories, p=[0.15, 0.20, 0.25, 0.20, 0.10, 0.10])
        city_tier = np.random.choice(city_tiers, p=[0.4, 0.4, 0.2])
        hospital_type = np.random.choice(hospital_types, p=[0.15, 0.45, 0.30, 0.10])

        if category in PER_UNIT_CATEGORIES:
            quantity = np.random.randint(1, 8)   # e.g. days admitted, tablets, tests
        else:
            quantity = 1

        base = CATEGORY_BASE_PRICE[category]
        price = (
            base
            * CITY_TIER_MULTIPLIER[city_tier]
            * HOSPITAL_TYPE_MULTIPLIER[hospital_type]
            * quantity
        )
        # add realistic random variation (+/- ~18%)
        price *= np.random.normal(loc=1.0, scale=0.18)
        price = max(price, base * 0.3)  # floor so noise never goes absurdly low

        rows.append({
            "category": category,
            "city_tier": city_tier,
            "hospital_type": hospital_type,
            "quantity": quantity,
            "fair_price": round(price, 2),
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = generate_pricing_dataset()
    df.to_csv("pricing_dataset.csv", index=False)
    print(f"Saved {len(df)} rows to pricing_dataset.csv")
    print(df.groupby("category")["fair_price"].describe().round(0))
