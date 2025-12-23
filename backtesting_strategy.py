#!/usr/bin/env python3
"""
Backtesting скрипт для оценки торговой стратегии BTC
Стратегия:
- Лонг BTC при индексе = 20, продажа при = 80
- Шорт BTC при индексе = 85 (плечо 1), закрытие при = 25
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
                print(f"Ошибка при получении данных {symbol} с Binance: {e}")
                break

        return all_klines

    @staticmethod
    def klines_to_dataframe(klines: List) -> pd.DataFrame:
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


class BTCTradingStrategy:
    """Класс для реализации торговой стратегии BTC с лонг и шорт позициями"""

    def __init__(self, initial_capital: float = 1000.0):
        self.initial_capital = initial_capital
        # Пороги для лонг позиций
        self.long_buy_threshold = 20
        self.long_sell_threshold = 80
        # Пороги для шорт позиций
        self.short_open_threshold = 85
        self.short_close_threshold = 25
        self.leverage = 1  # Плечо для шорта

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
        btc_holdings = 0.0  # Для лонг позиций
        short_position = 0.0  # Для шорт позиций (в BTC)
        short_entry_price = 0.0  # Цена входа в шорт
        trades = []
        portfolio_values = []
        in_long = False
        in_short = False

        # Симуляция торговли
        for idx, row in merged_data.iterrows():
            date = row['timestamp']
            price = row['close']
            fng_index = row['fear_greed_index']

            # Расчет текущей стоимости портфеля
            portfolio_value = cash + (btc_holdings * price)

            # Если есть шорт позиция, рассчитываем P&L
            if in_short:
                # P&L = (цена входа - текущая цена) × количество BTC в шорте
                short_pnl = (short_entry_price - price) * short_position
                portfolio_value = cash + short_pnl

            portfolio_values.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'btc_price': price,
                'fng_index': fng_index,
                'cash': cash,
                'btc_holdings': btc_holdings,
                'position_type': 'LONG' if in_long else ('SHORT' if in_short else 'NONE')
            })

            # ЛОНГ: Сигнал на покупку при индексе = 20
            if fng_index == self.long_buy_threshold and not in_long and not in_short and cash > 0:
                btc_amount = cash / price
                trades.append({
                    'date': date,
                    'type': 'BUY LONG',
                    'price': price,
                    'amount': btc_amount,
                    'value': cash,
                    'fng_index': fng_index
                })
                btc_holdings = btc_amount
                cash = 0
                in_long = True
                print(f"   📈 {date.strftime('%Y-%m-%d')}: ЛОНГ открыт при индексе {fng_index}, цена ${price:,.2f}")

            # ЛОНГ: Сигнал на продажу при индексе = 80
            elif fng_index == self.long_sell_threshold and in_long and btc_holdings > 0:
                sell_value = btc_holdings * price
                trades.append({
                    'date': date,
                    'type': 'SELL LONG',
                    'price': price,
                    'amount': btc_holdings,
                    'value': sell_value,
                    'fng_index': fng_index
                })
                cash = sell_value
                btc_holdings = 0
                in_long = False
                print(f"   📉 {date.strftime('%Y-%m-%d')}: ЛОНГ закрыт при индексе {fng_index}, цена ${price:,.2f}")

            # ШОРТ: Открытие шорт позиции при индексе = 85
            elif fng_index == self.short_open_threshold and not in_long and not in_short and cash > 0:
                # Открываем шорт на весь капитал с плечом 1
                # Занимаем BTC и продаем его
                short_btc_amount = cash / price * self.leverage
                short_position = short_btc_amount
                short_entry_price = price

                trades.append({
                    'date': date,
                    'type': 'OPEN SHORT',
                    'price': price,
                    'amount': short_btc_amount,
                    'value': cash,
                    'fng_index': fng_index
                })
                in_short = True
                print(f"   🔻 {date.strftime('%Y-%m-%d')}: ШОРТ открыт при индексе {fng_index}, цена ${price:,.2f}")

            # ШОРТ: Закрытие шорт позиции при индексе = 25
            elif fng_index == self.short_close_threshold and in_short and short_position > 0:
                # Закрываем шорт: выкупаем BTC
                buyback_cost = short_position * price
                profit = cash - buyback_cost
                final_cash = cash + profit

                trades.append({
                    'date': date,
                    'type': 'CLOSE SHORT',
                    'price': price,
                    'amount': short_position,
                    'value': final_cash,
                    'fng_index': fng_index,
                    'profit': profit
                })
                cash = final_cash
                short_position = 0
                short_entry_price = 0
                in_short = False
                print(f"   🔺 {date.strftime('%Y-%m-%d')}: ШОРТ закрыт при индексе {fng_index}, цена ${price:,.2f}, P&L: ${profit:,.2f}")

        # Закрытие позиций в конце периода
        final_price = merged_data.iloc[-1]['close']
        final_fng = merged_data.iloc[-1]['fear_greed_index']
        final_date = merged_data.iloc[-1]['timestamp']

        if btc_holdings > 0:
            final_value = btc_holdings * final_price
            trades.append({
                'date': final_date,
                'type': 'SELL LONG (Final)',
                'price': final_price,
                'amount': btc_holdings,
                'value': final_value,
                'fng_index': final_fng
            })
            cash = final_value
            btc_holdings = 0

        if short_position > 0:
            buyback_cost = short_position * final_price
            profit = cash - buyback_cost
            final_cash = cash + profit
            trades.append({
                'date': final_date,
                'type': 'CLOSE SHORT (Final)',
                'price': final_price,
                'amount': short_position,
                'value': final_cash,
                'fng_index': final_fng,
                'profit': profit
            })
            cash = final_cash
            short_position = 0

        return {
            'trades': trades,
            'portfolio_values': portfolio_values,
            'final_capital': cash
        }

    def calculate_statistics(self, backtest_results: Dict, price_data: pd.DataFrame) -> Dict:
        """Расчет детальной статистики торговли"""
        trades = backtest_results['trades']
        portfolio_values = pd.DataFrame(backtest_results['portfolio_values'])

        # Разделяем сделки по типам
        long_buy_trades = [t for t in trades if t['type'] == 'BUY LONG']
        long_sell_trades = [t for t in trades if 'SELL LONG' in t['type']]
        short_open_trades = [t for t in trades if t['type'] == 'OPEN SHORT']
        short_close_trades = [t for t in trades if 'CLOSE SHORT' in t['type']]

        # Расчет прибыльных сделок для лонгов
        profitable_longs = 0
        total_long_profit = 0
        total_long_loss = 0

        for i in range(min(len(long_buy_trades), len(long_sell_trades))):
            buy_price = long_buy_trades[i]['price']
            sell_price = long_sell_trades[i]['price']
            profit_pct = (sell_price - buy_price) / buy_price * 100

            if profit_pct > 0:
                profitable_longs += 1
                total_long_profit += profit_pct
            else:
                total_long_loss += abs(profit_pct)

        # Расчет прибыльных сделок для шортов
        profitable_shorts = 0
        total_short_profit = 0
        total_short_loss = 0

        for i in range(min(len(short_open_trades), len(short_close_trades))):
            open_price = short_open_trades[i]['price']
            close_price = short_close_trades[i]['price']
            profit_pct = (open_price - close_price) / open_price * 100  # Для шорта обратная логика

            if profit_pct > 0:
                profitable_shorts += 1
                total_short_profit += profit_pct
            else:
                total_short_loss += abs(profit_pct)

        total_cycles = len(long_buy_trades) + len(short_open_trades)
        profitable_cycles = profitable_longs + profitable_shorts
        win_rate = (profitable_cycles / total_cycles * 100) if total_cycles > 0 else 0

        # Максимальная просадка
        if not portfolio_values.empty:
            portfolio_values['peak'] = portfolio_values['portfolio_value'].cummax()
            portfolio_values['drawdown'] = (portfolio_values['portfolio_value'] - portfolio_values['peak']) / portfolio_values['peak'] * 100
            max_drawdown = portfolio_values['drawdown'].min()
        else:
            max_drawdown = 0

        # HODL стратегия для сравнения
        if not price_data.empty:
            first_price = price_data.iloc[0]['close']
            last_price = price_data.iloc[-1]['close']
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
            'long_cycles': len(long_buy_trades),
            'short_cycles': len(short_open_trades),
            'total_cycles': total_cycles,
            'profitable_cycles': profitable_cycles,
            'profitable_longs': profitable_longs,
            'profitable_shorts': profitable_shorts,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'initial_capital': self.initial_capital,
            'final_capital': backtest_results['final_capital'],
            'strategy_return': strategy_return,
            'hodl_final_value': hodl_final_value,
            'hodl_return': hodl_return,
            'outperformance': strategy_return - hodl_return,
            'long_profit_pct': total_long_profit,
            'long_loss_pct': total_long_loss,
            'short_profit_pct': total_short_profit,
            'short_loss_pct': total_short_loss,
            'portfolio_values': portfolio_values
        }


def print_results(stats: Dict, trades: List):
    """Вывод результатов бэктестинга"""
    print("\n" + "="*80)
    print("РЕЗУЛЬТАТЫ БЭКТЕСТИНГА ТОРГОВОЙ СТРАТЕГИИ BTC (ЛОНГ + ШОРТ)")
    print("="*80)

    print("\n📊 ПАРАМЕТРЫ СТРАТЕГИИ:")
    print(f"   Стартовый капитал: ${stats['initial_capital']:,.2f}")
    print(f"   ЛОНГ: Покупка при индексе = 20, продажа при = 80")
    print(f"   ШОРТ: Открытие при индексе = 85, закрытие при = 25 (плечо 1)")

    print("\n💰 ФИНАНСОВЫЕ РЕЗУЛЬТАТЫ:")
    print(f"   Финальный капитал: ${stats['final_capital']:,.2f}")
    print(f"   Прибыль стратегии: ${stats['final_capital'] - stats['initial_capital']:,.2f}")
    print(f"   Доходность стратегии: {stats['strategy_return']:.2f}%")

    print("\n📈 СРАВНЕНИЕ С HODL BTC:")
    print(f"   HODL BTC финальная стоимость: ${stats['hodl_final_value']:,.2f}")
    print(f"   HODL BTC доходность: {stats['hodl_return']:.2f}%")
    print(f"   Превосходство над HODL BTC: {stats['outperformance']:.2f}%")

    if stats['outperformance'] > 0:
        print(f"   ✅ Стратегия превзошла HODL на {stats['outperformance']:.2f}%")
    else:
        print(f"   ❌ Стратегия уступила HODL на {abs(stats['outperformance']):.2f}%")

    print("\n📊 СТАТИСТИКА СДЕЛОК:")
    print(f"   Всего сделок: {stats['total_trades']}")
    print(f"   Циклов ЛОНГ: {stats['long_cycles']}")
    print(f"   Циклов ШОРТ: {stats['short_cycles']}")
    print(f"   Всего циклов: {stats['total_cycles']}")
    print(f"   Прибыльных циклов: {stats['profitable_cycles']}")
    print(f"   Win Rate: {stats['win_rate']:.2f}%")

    print("\n⚠️  РИСКИ:")
    print(f"   Максимальная просадка: {stats['max_drawdown']:.2f}%")

    print("\n📋 ДЕТАЛИ СДЕЛОК:")
    print("-" * 80)
    for i, trade in enumerate(trades, 1):
        profit_str = f" | P&L: ${trade['profit']:,.2f}" if 'profit' in trade else ""
        print(f"{i}. {trade['date'].strftime('%Y-%m-%d')} | {trade['type']:20} | "
              f"Цена: ${trade['price']:,.2f} | "
              f"Сумма: ${trade['value']:,.2f} | "
              f"FG: {trade['fng_index']}{profit_str}")

    print("\n" + "="*80)


def main():
    """Основная функция"""
    print("🚀 Запуск бэктестинга торговой стратегии BTC (ЛОНГ + ШОРТ)...")

    # Параметры
    symbol = "BTCUSDT"
    interval = "1d"
    start_date = "2020-01-01"
    end_date = "2025-12-01"
    initial_capital = 1000.0

    # Конвертация дат в миллисекунды
    start_timestamp = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_timestamp = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

    print(f"\n📅 Период: {start_date} - {end_date}")
    print(f"💵 Стартовый капитал: ${initial_capital}")
    print(f"📊 Актив: BTC")

    # Получение данных BTC с Binance
    print(f"\n📊 Получение данных {symbol} с Binance...")
    binance = BinanceAPI()
    klines = binance.get_historical_klines(symbol, interval, start_timestamp, end_timestamp)
    price_data = binance.klines_to_dataframe(klines)
    print(f"✅ Получено {len(price_data)} дневных свечей")

    if price_data.empty:
        print("❌ Не удалось загрузить данные BTC. Проверьте подключение к интернету.")
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
    print(f"   ЛОНГ: индекс = 20 → покупка, индекс = 80 → продажа")
    print(f"   ШОРТ: индекс = 85 → открытие, индекс = 25 → закрытие")
    strategy = BTCTradingStrategy(initial_capital)
    backtest_results = strategy.backtest(price_data, fng_data)

    # Расчет статистики
    print(f"\n📈 Расчет статистики...")
    stats = strategy.calculate_statistics(backtest_results, price_data)

    # Вывод результатов
    print_results(stats, backtest_results['trades'])

    # Сохранение результатов
    output_file = "backtesting_results_btc.json"
    results_to_save = {
        'parameters': {
            'strategy': 'BTC Long/Short based on Fear & Greed Index',
            'symbol': symbol,
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': initial_capital,
            'long_buy': 20,
            'long_sell': 80,
            'short_open': 85,
            'short_close': 25,
            'leverage': 1
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
        csv_file = "portfolio_history_btc.csv"
        stats['portfolio_values'].to_csv(csv_file, index=False)
        print(f"💾 История портфеля сохранена в файл: {csv_file}")

    print("\n✅ Бэктестинг завершен успешно!")


if __name__ == "__main__":
    main()
