#!/usr/bin/env python3
"""
Backtesting скрипт для оценки торговой стратегии на основе индекса страха и жадности
Стратегия: покупка топ-20 криптовалют при индексе = 20, продажа при индексе = 80
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time
from typing import Dict, List, Tuple, Set
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


class CoinGeckoAPI:
    """Класс для работы с CoinGecko API"""

    BASE_URL = "https://api.coingecko.com/api/v3"

    # Список известных стейблкоинов для исключения
    STABLECOINS = {
        'usdt', 'usdc', 'busd', 'dai', 'tusd', 'usdd', 'usdp', 'gusd',
        'frax', 'lusd', 'susd', 'usdn', 'ust', 'husd', 'pax', 'usdj',
        'cusd', 'eurs', 'eurt', 'ustc', 'fei', 'tribe', 'ousd', 'musd',
        'nusd', 'dusd', 'vai', 'usx', 'dola', 'bean', 'mim', 'usdd',
        'usdk', 'RSV', 'flex usd', 'true usd', 'paxos standard'
    }

    @staticmethod
    def get_top_coins_with_supply(limit: int = 50) -> Dict[str, float]:
        """
        Получение топ монет с их circulating supply (исключая стейблкоины)

        Args:
            limit: Сколько монет запросить

        Returns:
            Словарь {symbol: circulating_supply}
        """
        session = get_session_without_proxy()

        try:
            url = f"{CoinGeckoAPI.BASE_URL}/coins/markets"
            params = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': limit,
                'page': 1,
                'sparkline': False
            }

            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Фильтруем стейблкоины и собираем данные
            coins_data = {}
            for coin in data:
                symbol = coin['symbol'].lower()
                name = coin['name'].lower()

                # Проверяем, не является ли монета стейблкоином
                is_stablecoin = False
                for stable in CoinGeckoAPI.STABLECOINS:
                    if stable in symbol or stable in name:
                        is_stablecoin = True
                        break

                if not is_stablecoin and coin.get('circulating_supply'):
                    coins_data[coin['symbol'].upper()] = float(coin['circulating_supply'])

            time.sleep(1.5)  # Rate limit для CoinGecko API
            return coins_data

        except Exception as e:
            print(f"Ошибка при получении данных монет CoinGecko: {e}")
            # Возвращаем резервный список с примерными supply
            # (это приблизительные значения для демонстрации)
            return {
                'BTC': 19500000, 'ETH': 120000000, 'BNB': 157000000,
                'XRP': 52000000000, 'ADA': 35000000000, 'SOL': 400000000,
                'DOGE': 140000000000, 'DOT': 1200000000, 'MATIC': 9000000000,
                'LTC': 73000000, 'SHIB': 589000000000000, 'TRX': 88000000000,
                'AVAX': 350000000, 'UNI': 750000000, 'LINK': 500000000,
                'ATOM': 290000000, 'XMR': 18000000, 'ETC': 140000000,
                'BCH': 19500000, 'XLM': 27000000000
            }


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
                print(f"Ошибка при получении данных {symbol} с Binance: {e}")
                break

        return all_klines

    @staticmethod
    def klines_to_dataframe(klines: List, symbol: str) -> pd.DataFrame:
        """Конвертация свечей в DataFrame"""
        if not klines:
            return pd.DataFrame()

        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['close'] = df['close'].astype(float)
        df['symbol'] = symbol

        return df[['timestamp', 'symbol', 'close']]

    @staticmethod
    def get_multiple_coins_data(symbols: List[str], interval: str, start_time: int, end_time: int) -> Dict[str, pd.DataFrame]:
        """
        Получение данных для нескольких монет

        Args:
            symbols: Список символов (например, ['BTC', 'ETH', 'BNB'])
            interval: Интервал
            start_time: Время начала
            end_time: Время окончания

        Returns:
            Словарь {symbol: DataFrame с ценами}
        """
        all_data = {}

        for symbol in symbols:
            trading_pair = f"{symbol}USDT"
            print(f"   Загрузка {trading_pair}...")

            klines = BinanceAPI.get_historical_klines(trading_pair, interval, start_time, end_time)
            if klines:
                df = BinanceAPI.klines_to_dataframe(klines, symbol)
                all_data[symbol] = df
            else:
                print(f"   ⚠️  Не удалось загрузить данные для {trading_pair}")

        return all_data


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


class PortfolioTradingStrategy:
    """Класс для реализации торговой стратегии с портфелем из топ-20 монет"""

    def __init__(self, initial_capital: float = 1000.0, buy_threshold: int = 20, sell_threshold: int = 80):
        self.initial_capital = initial_capital
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.allocation_per_coin = 0.05  # 5% на каждую монету

    def backtest(self, coins_data: Dict[str, pd.DataFrame], fng_data: pd.DataFrame,
                 coins_supply: Dict[str, float]) -> Dict:
        """
        Выполнение бэктестинга стратегии с портфелем монет

        Args:
            coins_data: Словарь {symbol: DataFrame с ценами}
            fng_data: DataFrame с индексом страха и жадности
            coins_supply: Словарь {symbol: circulating_supply}

        Returns:
            Словарь с результатами бэктестинга
        """
        # Подготовка данных - объединяем все цены в один DataFrame
        fng_data['date'] = fng_data['timestamp'].dt.date

        # Создаем общую временную шкалу
        all_dates = set()
        for df in coins_data.values():
            df['date'] = df['timestamp'].dt.date
            all_dates.update(df['date'].tolist())

        # Инициализация переменных
        cash = self.initial_capital
        portfolio = {}  # {symbol: amount}
        trades = []
        portfolio_values = []
        in_position = False

        # Сортируем даты
        sorted_dates = sorted(all_dates)

        # Симуляция торговли
        for current_date in sorted_dates:
            # Получаем индекс страха и жадности для текущей даты
            fng_row = fng_data[fng_data['date'] == current_date]
            if fng_row.empty:
                continue

            fng_index = fng_row.iloc[0]['fear_greed_index']
            timestamp = fng_row.iloc[0]['timestamp']

            # Получаем текущие цены всех монет
            current_prices = {}
            for symbol, df in coins_data.items():
                price_row = df[df['date'] == current_date]
                if not price_row.empty:
                    current_prices[symbol] = price_row.iloc[0]['close']

            # Расчет стоимости портфеля
            portfolio_value = cash
            for symbol, amount in portfolio.items():
                if symbol in current_prices:
                    portfolio_value += amount * current_prices[symbol]

            portfolio_values.append({
                'date': timestamp,
                'portfolio_value': portfolio_value,
                'fng_index': fng_index,
                'cash': cash,
                'positions': len(portfolio)
            })

            # Сигнал на покупку: индекс == 20 и нет позиции
            if fng_index == self.buy_threshold and not in_position and cash > 0:
                # Определяем топ-20 монет на текущую дату по капитализации
                market_caps = []
                for symbol, supply in coins_supply.items():
                    if symbol in current_prices:
                        price = current_prices[symbol]
                        market_cap = price * supply
                        market_caps.append({
                            'symbol': symbol,
                            'market_cap': market_cap,
                            'price': price
                        })

                # Сортируем по капитализации и берем топ-20
                market_caps.sort(key=lambda x: x['market_cap'], reverse=True)
                top_20_on_date = market_caps[:20]

                print(f"   📈 {timestamp.strftime('%Y-%m-%d')}: Топ-20 монет на дату: {', '.join([c['symbol'] for c in top_20_on_date[:10]])}...")

                # Покупаем топ-20 монет по 5% капитала на каждую
                amount_per_coin = cash * self.allocation_per_coin

                coins_bought = []
                total_spent = 0

                for coin_info in top_20_on_date:
                    symbol = coin_info['symbol']
                    price = coin_info['price']
                    coin_amount = amount_per_coin / price
                    portfolio[symbol] = coin_amount

                    trades.append({
                        'date': timestamp,
                        'type': 'BUY',
                        'symbol': symbol,
                        'price': price,
                        'amount': coin_amount,
                        'value': amount_per_coin,
                        'fng_index': fng_index
                    })

                    coins_bought.append(symbol)
                    total_spent += amount_per_coin

                cash -= total_spent
                in_position = True
                print(f"   ✅ Куплено {len(coins_bought)} монет при индексе {fng_index}")

            # Сигнал на продажу: индекс == 80 и есть позиции
            elif fng_index == self.sell_threshold and in_position and portfolio:
                total_received = 0
                coins_sold = []

                for symbol, amount in portfolio.items():
                    if symbol in current_prices:
                        price = current_prices[symbol]
                        sell_value = amount * price

                        trades.append({
                            'date': timestamp,
                            'type': 'SELL',
                            'symbol': symbol,
                            'price': price,
                            'amount': amount,
                            'value': sell_value,
                            'fng_index': fng_index
                        })

                        total_received += sell_value
                        coins_sold.append(symbol)

                cash += total_received
                portfolio = {}
                in_position = False
                print(f"   📉 {timestamp.strftime('%Y-%m-%d')}: Продано {len(coins_sold)} монет при индексе {fng_index}")

        # Закрытие позиций в конце периода
        if portfolio:
            final_date = sorted_dates[-1]
            fng_row = fng_data[fng_data['date'] == final_date]
            final_fng = fng_row.iloc[0]['fear_greed_index'] if not fng_row.empty else 50
            final_timestamp = fng_row.iloc[0]['timestamp'] if not fng_row.empty else timestamp

            total_received = 0
            for symbol, amount in portfolio.items():
                if symbol in coins_data:
                    final_price_row = coins_data[symbol][coins_data[symbol]['date'] == final_date]
                    if not final_price_row.empty:
                        final_price = final_price_row.iloc[0]['close']
                        sell_value = amount * final_price

                        trades.append({
                            'date': final_timestamp,
                            'type': 'SELL (Final)',
                            'symbol': symbol,
                            'price': final_price,
                            'amount': amount,
                            'value': sell_value,
                            'fng_index': final_fng
                        })

                        total_received += sell_value

            cash += total_received
            portfolio = {}

        return {
            'trades': trades,
            'portfolio_values': portfolio_values,
            'final_capital': cash
        }

    def calculate_statistics(self, backtest_results: Dict, coins_data: Dict[str, pd.DataFrame]) -> Dict:
        """Расчет детальной статистики торговли"""
        trades = backtest_results['trades']
        portfolio_values = pd.DataFrame(backtest_results['portfolio_values'])

        # Основные метрики
        buy_trades = [t for t in trades if t['type'] == 'BUY']
        sell_trades = [t for t in trades if t['type'].startswith('SELL')]

        # Группируем сделки по циклам покупка-продажа
        unique_dates_buy = list(set([t['date'] for t in buy_trades]))
        unique_dates_sell = list(set([t['date'] for t in sell_trades]))

        trade_cycles = min(len(unique_dates_buy), len(unique_dates_sell))

        # Расчет прибыльности по циклам
        profitable_cycles = 0
        total_profit = 0
        total_loss = 0

        for i in range(trade_cycles):
            buy_date = sorted(unique_dates_buy)[i]
            sell_date = sorted(unique_dates_sell)[i]

            buy_value = sum([t['value'] for t in buy_trades if t['date'] == buy_date])
            sell_value = sum([t['value'] for t in sell_trades if t['date'] == sell_date])

            profit_pct = (sell_value - buy_value) / buy_value * 100

            if profit_pct > 0:
                profitable_cycles += 1
                total_profit += profit_pct
            else:
                total_loss += abs(profit_pct)

        win_rate = (profitable_cycles / trade_cycles * 100) if trade_cycles > 0 else 0

        # Максимальная просадка
        if not portfolio_values.empty:
            portfolio_values['peak'] = portfolio_values['portfolio_value'].cummax()
            portfolio_values['drawdown'] = (portfolio_values['portfolio_value'] - portfolio_values['peak']) / portfolio_values['peak'] * 100
            max_drawdown = portfolio_values['drawdown'].min()
        else:
            max_drawdown = 0

        # HODL стратегия для BTC (для сравнения)
        if 'BTC' in coins_data and not coins_data['BTC'].empty:
            btc_data = coins_data['BTC']
            first_price = btc_data.iloc[0]['close']
            last_price = btc_data.iloc[-1]['close']
            hodl_btc = self.initial_capital / first_price
            hodl_final_value = hodl_btc * last_price
            hodl_return = (hodl_final_value - self.initial_capital) / self.initial_capital * 100
        else:
            hodl_final_value = self.initial_capital
            hodl_return = 0

        # Доходность стратегии
        strategy_return = (backtest_results['final_capital'] - self.initial_capital) / self.initial_capital * 100

        return {
            'total_trades': len(trades),
            'buy_trades': len(buy_trades),
            'sell_trades': len(sell_trades),
            'trade_cycles': trade_cycles,
            'profitable_cycles': profitable_cycles,
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
            'avg_profit_per_cycle': total_profit / profitable_cycles if profitable_cycles > 0 else 0,
            'portfolio_values': portfolio_values
        }


def print_results(stats: Dict, trades: List):
    """Вывод результатов бэктестинга"""
    print("\n" + "="*80)
    print("РЕЗУЛЬТАТЫ БЭКТЕСТИНГА ТОРГОВОЙ СТРАТЕГИИ (TOP-20 ПОРТФЕЛЬ)")
    print("="*80)

    print("\n📊 ПАРАМЕТРЫ СТРАТЕГИИ:")
    print(f"   Стартовый капитал: ${stats['initial_capital']:,.2f}")
    print(f"   Сигнал покупки: Индекс страха = 20 (Extreme Fear)")
    print(f"   Сигнал продажи: Индекс страха = 80 (Extreme Greed)")
    print(f"   Распределение: 5% капитала на каждую монету из топ-20")

    print("\n💰 ФИНАНСОВЫЕ РЕЗУЛЬТАТЫ:")
    print(f"   Финальный капитал: ${stats['final_capital']:,.2f}")
    print(f"   Прибыль стратегии: ${stats['final_capital'] - stats['initial_capital']:,.2f}")
    print(f"   Доходность стратегии: {stats['strategy_return']:.2f}%")

    print("\n📈 СРАВНЕНИЕ С HODL BTC:")
    print(f"   HODL BTC финальная стоимость: ${stats['hodl_final_value']:,.2f}")
    print(f"   HODL BTC доходность: {stats['hodl_return']:.2f}%")
    print(f"   Превосходство над HODL BTC: {stats['outperformance']:.2f}%")

    if stats['outperformance'] > 0:
        print(f"   ✅ Стратегия превзошла HODL BTC на {stats['outperformance']:.2f}%")
    else:
        print(f"   ❌ Стратегия уступила HODL BTC на {abs(stats['outperformance']):.2f}%")

    print("\n📊 СТАТИСТИКА СДЕЛОК:")
    print(f"   Всего сделок: {stats['total_trades']}")
    print(f"   Циклов покупка-продажа: {stats['trade_cycles']}")
    print(f"   Прибыльных циклов: {stats['profitable_cycles']}")
    print(f"   Win Rate: {stats['win_rate']:.2f}%")
    print(f"   Средняя прибыль на цикл: {stats['avg_profit_per_cycle']:.2f}%")

    print("\n⚠️  РИСКИ:")
    print(f"   Максимальная просадка: {stats['max_drawdown']:.2f}%")

    # Группируем сделки по датам
    print("\n📋 ЦИКЛЫ ТОРГОВЛИ:")
    print("-" * 80)

    buy_trades = [t for t in trades if t['type'] == 'BUY']
    sell_trades = [t for t in trades if t['type'].startswith('SELL')]

    buy_dates = sorted(set([t['date'] for t in buy_trades]))
    sell_dates = sorted(set([t['date'] for t in sell_trades]))

    for i, buy_date in enumerate(buy_dates):
        buy_coins = [t for t in buy_trades if t['date'] == buy_date]
        buy_value = sum([t['value'] for t in buy_coins])

        print(f"\nЦикл {i+1}:")
        print(f"  📈 ПОКУПКА {buy_date.strftime('%Y-%m-%d')}:")
        print(f"     Куплено монет: {len(buy_coins)}")
        print(f"     Общая сумма: ${buy_value:,.2f}")
        print(f"     Монеты: {', '.join([t['symbol'] for t in buy_coins[:10]])}" +
              (f"... (+{len(buy_coins)-10})" if len(buy_coins) > 10 else ""))

        if i < len(sell_dates):
            sell_date = sell_dates[i]
            sell_coins = [t for t in sell_trades if t['date'] == sell_date]
            sell_value = sum([t['value'] for t in sell_coins])
            profit = sell_value - buy_value
            profit_pct = (profit / buy_value) * 100

            print(f"  📉 ПРОДАЖА {sell_date.strftime('%Y-%m-%d')}:")
            print(f"     Продано монет: {len(sell_coins)}")
            print(f"     Общая сумма: ${sell_value:,.2f}")
            print(f"     Прибыль: ${profit:,.2f} ({profit_pct:+.2f}%)")

    print("\n" + "="*80)


def main():
    """Основная функция"""
    print("🚀 Запуск бэктестинга торговой стратегии с TOP-20 портфелем...")

    # Параметры
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
    print(f"📊 Стратегия: покупка топ-20 монет по 5% каждая")

    # Получение топ монет с их circulating supply
    print(f"\n🏆 Получение топ-50 монет с данными о supply (без стейблкоинов)...")
    coingecko = CoinGeckoAPI()
    coins_supply = coingecko.get_top_coins_with_supply(limit=50)
    all_symbols = list(coins_supply.keys())
    print(f"✅ Получено {len(all_symbols)} монет: {', '.join(all_symbols[:10])}... (+{len(all_symbols)-10} монет)")

    # Получение данных для всех монет
    print(f"\n📊 Получение исторических данных для {len(all_symbols)} монет с Binance...")
    coins_data = BinanceAPI.get_multiple_coins_data(all_symbols, interval, start_timestamp, end_timestamp)
    print(f"✅ Загружено данных для {len(coins_data)} монет")

    if not coins_data:
        print("❌ Не удалось загрузить данные монет. Проверьте подключение к интернету.")
        return

    # Получение данных Fear & Greed Index
    print(f"\n😱 Получение данных индекса страха и жадности...")
    fng_api = FearGreedAPI()
    fng_data = fng_api.get_historical_data(limit=0)
    print(f"✅ Получено {len(fng_data)} записей индекса")

    if fng_data.empty:
        print("❌ Не удалось загрузить данные индекса страха и жадности.")
        return

    # Выполнение бэктестинга
    print(f"\n⚡ Выполнение бэктестинга стратегии...")
    print(f"   На каждую дату покупки (индекс = 20) будет определяться топ-20 по капитализации")
    strategy = PortfolioTradingStrategy(initial_capital, buy_threshold, sell_threshold)
    backtest_results = strategy.backtest(coins_data, fng_data, coins_supply)

    # Расчет статистики
    print(f"\n📈 Расчет статистики...")
    stats = strategy.calculate_statistics(backtest_results, coins_data)

    # Вывод результатов
    print_results(stats, backtest_results['trades'])

    # Сохранение результатов
    output_file = "backtesting_results_top20.json"

    # Собираем уникальные монеты, которые были куплены во всех циклах
    all_bought_coins = set()
    for trade in backtest_results['trades']:
        if trade['type'] == 'BUY':
            all_bought_coins.add(trade['symbol'])

    results_to_save = {
        'parameters': {
            'strategy': 'Dynamic TOP-20 selection on buy signal',
            'coins_pool_size': len(all_symbols),
            'all_bought_coins': sorted(list(all_bought_coins)),
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': initial_capital,
            'buy_threshold': buy_threshold,
            'sell_threshold': sell_threshold,
            'allocation_per_coin': 0.05
        },
        'statistics': {k: v for k, v in stats.items() if k != 'portfolio_values'},
        'trades': backtest_results['trades']
    }

    # Конвертация datetime в строки
    for trade in results_to_save['trades']:
        trade['date'] = trade['date'].strftime('%Y-%m-%d %H:%M:%S')

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results_to_save, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n💾 Результаты сохранены в файл: {output_file}")

    # Сохранение CSV
    if not stats['portfolio_values'].empty:
        csv_file = "portfolio_history_top20.csv"
        stats['portfolio_values'].to_csv(csv_file, index=False)
        print(f"💾 История портфеля сохранена в файл: {csv_file}")

    print("\n✅ Бэктестинг завершен успешно!")


if __name__ == "__main__":
    main()
