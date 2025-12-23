#!/usr/bin/env python3
"""Анализ значений индекса страха и жадности"""

import requests
import pandas as pd


def get_session_without_proxy():
    """Создание сессии без прокси"""
    session = requests.Session()
    session.trust_env = False
    session.proxies = {
        'http': None,
        'https': None,
    }
    return session


def analyze_fear_greed_index():
    """Анализ индекса страха и жадности"""
    print("📊 Загрузка данных индекса страха и жадности...\n")

    session = get_session_without_proxy()
    response = session.get("https://api.alternative.me/fng/?limit=0", timeout=30)
    data = response.json()

    df = pd.DataFrame(data['data'])
    df['value'] = df['value'].astype(int)

    print(f"Всего записей: {len(df)}")
    print(f"\nМинимальное значение: {df['value'].min()}")
    print(f"Максимальное значение: {df['value'].max()}")

    print(f"\n=== ПРОВЕРКА ТОЧНЫХ ЗНАЧЕНИЙ ===")
    print(f"Индекс = 85: {len(df[df['value'] == 85])} раз")
    print(f"Индекс = 25: {len(df[df['value'] == 25])} раз")
    print(f"Индекс = 20: {len(df[df['value'] == 20])} раз")
    print(f"Индекс = 80: {len(df[df['value'] == 80])} раз")

    print(f"\n=== ВЫСОКИЕ ЗНАЧЕНИЯ (>= 80) ===")
    high = df[df['value'] >= 80]['value'].value_counts().sort_index(ascending=False)
    print(high.head(20))

    print(f"\n=== НИЗКИЕ ЗНАЧЕНИЯ (<= 30) ===")
    low = df[df['value'] <= 30]['value'].value_counts().sort_index()
    print(low.head(20))

    print(f"\n=== ДИАПАЗОН 83-87 (вокруг 85) ===")
    around_85 = df[(df['value'] >= 83) & (df['value'] <= 87)]['value'].value_counts().sort_index()
    print(around_85)


if __name__ == "__main__":
    analyze_fear_greed_index()
