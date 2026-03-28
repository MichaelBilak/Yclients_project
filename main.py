import argparse
import sys

from sync_orchestrator import run_sync_job


def parse_args():
    parser = argparse.ArgumentParser(description='YClients BI sync runner')
    parser.add_argument(
        '--mode',
        choices=['incremental', 'full'],
        default='incremental',
        help='Тип синхронизации',
    )
    parser.add_argument(
        '--trigger',
        choices=['scheduled', 'manual'],
        default='manual',
        help='Источник запуска',
    )
    parser.add_argument(
        '--initiator',
        default='system',
        help='Инициатор запуска для аудита и статуса',
    )
    return parser.parse_args()


def main():
    args = parse_args()
    result = run_sync_job(
        mode=args.mode,
        trigger_type=args.trigger,
        initiator=args.initiator,
    )

    if result.get('status') == 'already_running':
        print('Синхронизация уже выполняется, новый запуск отклонен')
        return 2

    if result.get('status') != 'success':
        print(f"Синхронизация завершилась со статусом {result.get('status')}")
        return 1

    print(f"Синхронизация завершена успешно. Лог: {result.get('log_path')}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
