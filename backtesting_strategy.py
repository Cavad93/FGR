#!/usr/bin/env python3
"""
Backtesting скрипт для оценки торговой стратегии на основе индекса страха и жадности
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time
from typing import Dict, List, Tuple
import json
import os


def get_session_without_proxy():
    """Создание сессии без прокси"""
    session = requests.Session()
    session.trust_env = False
    session.proxies = {
        'http': None,
        'https': None,
    }
    return session


class BinanceAPI:
    """Класс для работы с Binance API"""

    BASE_URL = "https://api.binance.com/api/v3"

    @staticmethod
    def get_historical_klines(symbol: str, interval: str, start_time: int, end_time: int) -> List:
        """
        Получение исторических данных свечей

        Args:
            symbol: Торговая пара (например, 'BTCUSDT')
            interval: Интервал (например, '1d' для дневных свечей)
            start_time: Время начала в миллисекундах
            end_time: Время окончания в миллисекундах
        """
        url = f"{BinanceAPI.BASE_URL}/klines"

        all_klines = []
        current_start = start_time
        session = get_session_without_proxy()

        while current_start < end_time:
            params = {
                'symbol': symbol,
                'interval': interval,
                'startTime': current_start,
                'endTime': end_time,
                'limit': 1000  # Максимум 1000 свечей за запрос
            }

            try:
                response = session.get(url, params=params, timeout=30)
                response.raise_for_status()
                klines = response.json()

                if not klines:
                    break

                all_klines.extend(klines)
                current_start = klines[-1][0] + 1  # Следующий запрос начинается после последней свечи

                time.sleep(0.5)  # Задержка для избежания rate limit

            except Exception as e:
                print(f"Ошибка при получении данных Binance: {e}")
                break

        return all_klines

    @staticmethod
    def klines_to_dataframe(klines: List) -> pd.DataFrame:
        """Конвертация свечей в DataFrame"""
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['close'] = df['close'].astype(float)
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)

        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]


class FearGreedAPI:
    """Класс для работы с API индекса страха и жадности"""

    BASE_URL = "https://api.alternative.me/fng/"

    @staticmethod
    def get_historical_data(limit: int = 0) -> pd.DataFrame:
        """
        Получение исторических данных индекса страха и жадности

        Args:
            limit: Количество дней (0 = все доступные данные)
        """
        params = {'limit': limit} if limit > 0 else {'limit': 0}
        session = get_session_without_proxy()

        try:
            response = session.get(FearGreedAPI.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data['metadata']['error'] is not None:
                raise Exception(f"API Error: {data['metadata']['error']}")

            df = pd.DataFrame(data['data'])
            df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='s')
            df['value'] = df['value'].astype(int)
            df = df.rename(columns={'value': 'fear_greed_index'})
            df = df[['timestamp', 'fear_greed_index', 'value_classification']]
            df = df.sort_values('timestamp').reset_index(drop=True)

            return df

        except Exception as e:
            print(f"Ошибка при получении данных Fear & Greed Index: {e}")
            return pd.DataFrame()


class TradingStrategy:
    """Класс для реализации торговой стратегии"""

    def __init__(self, initial_capital: float = 1000.0, buy_threshold: int = 20, sell_threshold: int = 80):
        self.initial_capital = initial_capital
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def backtest(self, price_data: pd.DataFrame, fng_data: pd.DataFrame) -> Dict:
        """
        Выполнение бэктестинга стратегии

        Args:
            price_data: DataFrame с историческими ценами BTC
            fng_data: DataFrame с индексом страха и жадности

        Returns:
            Словарь с результатами бэктестинга
        """
        # Объединение данных по датам
        price_data['date'] = price_data['timestamp'].dt.date
        fng_data['date'] = fng_data['timestamp'].dt.date

        merged_data = pd.merge(
            price_data,
            fng_data[['date', 'fear_greed_index']],
            on='date',
            how='inner'
        )

        # Инициализация переменных
        cash = self.initial_capital
        btc_holdings = 0.0
        trades = []
        portfolio_values = []
        in_position = False

        # Симуляция торговли
        for idx, row in merged_data.iterrows():
            date = row['timestamp']
            price = row['close']
            fng_index = row['fear_greed_index']

            # Расчет текущей стоимости портфеля
            portfolio_value = cash + (btc_holdings * price)
            portfolio_values.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'btc_price': price,
                'fng_index': fng_index,
                'cash': cash,
                'btc_holdings': btc_holdings
            })

            # Сигнал на покупку: индекс < 20 и нет позиции
            if fng_index < self.buy_threshold and not in_position and cash > 0:
                btc_amount = cash / price
                trades.append({
                    'date': date,
                    'type': 'BUY',
                    'price': price,
                    'amount': btc_amount,
                    'value': cash,
                    'fng_index': fng_index
                })
                btc_holdings = btc_amount
                cash = 0
                in_position = True

            # Сигнал на продажу: индекс > 80 и есть позиция
            elif fng_index > self.sell_threshold and in_position and btc_holdings > 0:
                sell_value = btc_holdings * price
                trades.append({
                    'date': date,
                    'type': 'SELL',
                    'price': price,
                    'amount': btc_holdings,
                    'value': sell_value,
                    'fng_index': fng_index
                })
                cash = sell_value
                btc_holdings = 0
                in_position = False

        # Закрытие позиции в конце периода, если она открыта
        if btc_holdings > 0:
            final_price = merged_data.iloc[-1]['close']
            final_value = btc_holdings * final_price
            trades.append({
                'date': merged_data.iloc[-1]['timestamp'],
                'type': 'SELL (Final)',
                'price': final_price,
                'amount': btc_holdings,
                'value': final_value,
                'fng_index': merged_data.iloc[-1]['fear_greed_index']
            })
            cash = final_value
            btc_holdings = 0

        return {
            'trades': trades,
            'portfolio_values': portfolio_values,
            'final_capital': cash,
            'merged_data': merged_data
        }

    def calculate_statistics(self, backtest_results: Dict, price_data: pd.DataFrame) -> Dict:
        """Расчет детальной статистики торговли"""
        trades = backtest_results['trades']
        portfolio_values = pd.DataFrame(backtest_results['portfolio_values'])

        # Основные метрики
        total_trades = len([t for t in trades if t['type'] in ['BUY', 'SELL']])
        buy_trades = [t for t in trades if t['type'] == 'BUY']
        sell_trades = [t for t in trades if t['type'].startswith('SELL')]

        # Расчет прибыльных сделок
        profitable_trades = 0
        total_profit = 0
        total_loss = 0

        for i in range(len(buy_trades)):
            if i < len(sell_trades):
                buy_price = buy_trades[i]['price']
                sell_price = sell_trades[i]['price']
                profit = (sell_price - buy_price) / buy_price * 100

                if profit > 0:
                    profitable_trades += 1
                    total_profit += profit
                else:
                    total_loss += abs(profit)

        win_rate = (profitable_trades / len(buy_trades) * 100) if buy_trades else 0

        # Максимальная просадка (drawdown)
        portfolio_values['peak'] = portfolio_values['portfolio_value'].cummax()
        portfolio_values['drawdown'] = (portfolio_values['portfolio_value'] - portfolio_values['peak']) / portfolio_values['peak'] * 100
        max_drawdown = portfolio_values['drawdown'].min()

        # HODL стратегия для сравнения
        first_price = price_data.iloc[0]['close']
        last_price = price_data.iloc[-1]['close']
        hodl_btc = self.initial_capital / first_price
        hodl_final_value = hodl_btc * last_price
        hodl_return = (hodl_final_value - self.initial_capital) / self.initial_capital * 100

        # Доходность стратегии
        strategy_return = (backtest_results['final_capital'] - self.initial_capital) / self.initial_capital * 100

        return {
            'total_trades': total_trades,
            'buy_trades': len(buy_trades),
            'sell_trades': len(sell_trades),
            'profitable_trades': profitable_trades,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'initial_capital': self.initial_capital,
            'final_capital': backtest_results['final_capital'],
            'strategy_return': strategy_return,
            'hodl_final_value': hodl_final_value,
            'hodl_return': hodl_return,
            'outperformance': strategy_return - hodl_return,
            'total_profit_pct': total_profit,
            'total_loss_pct': total_loss,
            'avg_profit_per_trade': total_profit / profitable_trades if profitable_trades > 0 else 0,
            'portfolio_values': portfolio_values
        }


def print_results(stats: Dict, trades: List):
    """Вывод результатов бэктестинга"""
    print("\n" + "="*80)
    print("РЕЗУЛЬТАТЫ БЭКТЕСТИНГА ТОРГОВОЙ СТРАТЕГИИ")
    print("="*80)

    print("\n📊 ПАРАМЕТРЫ СТРАТЕГИИ:")
    print(f"   Стартовый капитал: ${stats['initial_capital']:,.2f}")
    print(f"   Сигнал покупки: Индекс страха < 20 (Extreme Fear)")
    print(f"   Сигнал продажи: Индекс страха > 80 (Extreme Greed)")

    print("\n💰 ФИНАНСОВЫЕ РЕЗУЛЬТАТЫ:")
    print(f"   Финальный капитал: ${stats['final_capital']:,.2f}")
    print(f"   Прибыль стратегии: ${stats['final_capital'] - stats['initial_capital']:,.2f}")
    print(f"   Доходность стратегии: {stats['strategy_return']:.2f}%")

    print("\n📈 СРАВНЕНИЕ С HODL:")
    print(f"   HODL финальная стоимость: ${stats['hodl_final_value']:,.2f}")
    print(f"   HODL доходность: {stats['hodl_return']:.2f}%")
    print(f"   Превосходство над HODL: {stats['outperformance']:.2f}%")

    if stats['outperformance'] > 0:
        print(f"   ✅ Стратегия превзошла HODL на {stats['outperformance']:.2f}%")
    else:
        print(f"   ❌ Стратегия уступила HODL на {abs(stats['outperformance']):.2f}%")

    print("\n📊 СТАТИСТИКА СДЕЛОК:")
    print(f"   Всего сделок: {stats['total_trades']}")
    print(f"   Покупок: {stats['buy_trades']}")
    print(f"   Продаж: {stats['sell_trades']}")
    print(f"   Прибыльных сделок: {stats['profitable_trades']}")
    print(f"   Win Rate: {stats['win_rate']:.2f}%")
    print(f"   Средняя прибыль на сделку: {stats['avg_profit_per_trade']:.2f}%")

    print("\n⚠️  РИСКИ:")
    print(f"   Максимальная просадка: {stats['max_drawdown']:.2f}%")

    print("\n📋 ДЕТАЛИ СДЕЛОК:")
    print("-" * 80)
    for i, trade in enumerate(trades, 1):
        print(f"{i}. {trade['date'].strftime('%Y-%m-%d')} | {trade['type']:15} | "
              f"Цена: ${trade['price']:,.2f} | "
              f"Сумма: ${trade['value']:,.2f} | "
              f"FG Index: {trade['fng_index']}")

    print("\n" + "="*80)


def main():
    """Основная функция"""
    print("🚀 Запуск бэктестинга торговой стратегии...")

    # Параметры
    symbol = "BTCUSDT"
    interval = "1d"
    start_date = "2020-01-01"
    end_date = "2025-12-01"
    initial_capital = 1000.0
    buy_threshold = 20
    sell_threshold = 80

    # Конвертация дат в миллисекунды
    start_timestamp = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_timestamp = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

    print(f"\n📅 Период: {start_date} - {end_date}")
    print(f"💵 Стартовый капитал: ${initial_capital}")

    # Получение данных с Binance
    print(f"\n📊 Получение данных BTCUSDT с Binance...")
    binance = BinanceAPI()
    klines = binance.get_historical_klines(symbol, interval, start_timestamp, end_timestamp)
    price_data = binance.klines_to_dataframe(klines)
    print(f"✅ Получено {len(price_data)} дневных свечей")

    # Получение данных Fear & Greed Index
    print(f"\n😱 Получение данных индекса страха и жадности...")
    fng_api = FearGreedAPI()
    fng_data = fng_api.get_historical_data(limit=0)
    print(f"✅ Получено {len(fng_data)} записей индекса")

    # Выполнение бэктестинга
    print(f"\n⚡ Выполнение бэктестинга стратегии...")
    strategy = TradingStrategy(initial_capital, buy_threshold, sell_threshold)
    backtest_results = strategy.backtest(price_data, fng_data)

    # Расчет статистики
    print(f"\n📈 Расчет статистики...")
    stats = strategy.calculate_statistics(backtest_results, price_data)

    # Вывод результатов
    print_results(stats, backtest_results['trades'])

    # Сохранение результатов в JSON
    output_file = "backtesting_results.json"
    results_to_save = {
        'parameters': {
            'symbol': symbol,
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': initial_capital,
            'buy_threshold': buy_threshold,
            'sell_threshold': sell_threshold
        },
        'statistics': {k: v for k, v in stats.items() if k != 'portfolio_values'},
        'trades': backtest_results['trades']
    }

    # Конвертация datetime объектов в строки
    for trade in results_to_save['trades']:
        trade['date'] = trade['date'].strftime('%Y-%m-%d %H:%M:%S')

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results_to_save, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n💾 Результаты сохранены в файл: {output_file}")

    # Сохранение CSV с историей портфеля
    csv_file = "portfolio_history.csv"
    stats['portfolio_values'].to_csv(csv_file, index=False)
    print(f"💾 История портфеля сохранена в файл: {csv_file}")

    print("\n✅ Бэктестинг завершен успешно!")


if __name__ == "__main__":
    main()
