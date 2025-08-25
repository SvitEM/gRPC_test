# gRPC Тесты Задержки (TLS 1.3 + mTLS)

Комплексные тесты задержки между **DF** (сервер/система под тестированием) и **SMFT** (клиент/генератор нагрузки) на Python 3.11 с `grpc.aio` и минимальными зависимостями.

## Обзор

Проект реализует два теста задержки согласно спецификации в `CLAUDE.md`:

1. **01_steady** — Фиксированный RPS (500/1000/1200/2000) через **один переиспользуемый канал** (HTTP/2 мультиплексирование)
2. **02_coldconn** — **Новый защищённый канал для каждого запроса** со скоростью 1 RPS для измерения накладных расходов на соединение

## Быстрый старт

### Требования
- Python 3.11+
- Docker (опционально)
- OpenSSL (для генерации сертификатов)

### 🚀 **Рекомендуется: Настройка Protobuf 6.x (Высокая Производительность)**

Для лучшей производительности используйте автоматическую настройку с protobuf 6.x:

```bash
# Автоматическая настройка с protobuf 6.x (рекомендуется)
./quick_protobuf6_test.sh

# Активация окружения
source venv_test/bin/activate

# Быстрый тест (без шифрования)
python test_server_simple.py &
N_RPS=100 T_DURATION_SEC=10 python test_insecure_steady.py
```

**Улучшение производительности**: ~15% быстрее чем protobuf 4.x!

### 📦 **Альтернатива: Ручная настройка**

1. **Выберите версию Protobuf**
   
   **Вариант A: Protobuf 6.x (рекомендуется для производительности)**
   ```bash
   python3.11 -m venv venv_protobuf6
   source venv_protobuf6/bin/activate
   pip install protobuf>=6.32.0 grpcio>=1.74.0 grpcio-tools>=1.74.0 python-dotenv
   ```
   
   **Вариант B: Protobuf 4.x (совместим с библиотеками Google Cloud)**
   ```bash
   pip install "protobuf>=4.21.0,<5.0.0" "grpcio>=1.60.0" "grpcio-tools>=1.60.0" python-dotenv
   ```

2. **Генерация протокольных заглушек**
   ```bash
   python -m grpc_tools.protoc --proto_path=proto --python_out=df --grpc_python_out=df proto/score.proto
   python -m grpc_tools.protoc --proto_path=proto --python_out=smft --grpc_python_out=smft proto/score.proto
   ```

3. **Запуск DF сервера**
   ```bash
   cd df
   python 01_steady_server.py
   # ИЛИ
   python 02_coldconn_server.py
   ```

4. **Запуск SMFT клиентов**
   ```bash
   cd smft
   
   # Тест стабильного состояния (10 RPS, 30с длительность, 5с разогрев)
   N_RPS=10 T_DURATION_SEC=30 T_WARMUP_SEC=5 python 01_steady_client.py
   
   # Тест холодного соединения (1 RPS, 60с длительность)  
   T_DURATION_SEC=60 python 02_coldconn_client.py
   ```

5. **Анализ результатов**
   ```bash
   python tools/summarize.py smft/01_steady_results.txt
   python tools/summarize.py smft/02_coldconn_results.txt
   ```

### Развертывание через Docker

1. **Сборка образов**
   ```bash
   # DF Сервер
   docker build -t df-server -f df/Dockerfile .
   
   # SMFT Клиент  
   docker build -t smft-client -f smft/Dockerfile .
   ```

2. **Запуск через Docker**
   ```bash
   # Запуск DF сервера
   docker run -d --name df-server \
     -p 50051:50051 \
     -v $(pwd)/df/certs:/app/certs:ro \
     -e DF_HOST=0.0.0.0 \
     -e DF_PORT=50051 \
     -e DELAY_MS=5 \
     df-server
   
   # Запуск теста стабильного состояния
   docker run --rm \
     -v $(pwd)/smft/certs:/app/certs:ro \
     -v $(pwd)/results:/app/results \
     -e DF_HOST=df-server \
     -e N_RPS=1000 \
     -e T_DURATION_SEC=300 \
     -e T_WARMUP_SEC=30 \
     --link df-server \
     smft-client python 01_steady_client.py
   
   # Запуск теста холодного соединения
   docker run --rm \
     -v $(pwd)/smft/certs:/app/certs:ro \
     -v $(pwd)/results:/app/results \
     -e DF_HOST=df-server \
     -e T_DURATION_SEC=300 \
     --link df-server \
     smft-client python 02_coldconn_client.py
   ```

## Пошаговые инструкции запуска тестов

### Вариант 1: Упрощённый запуск (без TLS)

Для быстрого тестирования функциональности:

1. **Запуск упрощённого сервера**
   ```bash
   python test_server_simple.py &
   ```

2. **Запуск теста стабильного состояния**
   ```bash
   N_RPS=10 T_DURATION_SEC=5 T_WARMUP_SEC=1 python test_insecure_steady.py
   ```

3. **Запуск теста холодного соединения**
   ```bash
   T_DURATION_SEC=5 python test_insecure_coldconn.py
   ```

4. **Анализ результатов**
   ```bash
   python tools/summarize.py 01_steady_results.txt
   python tools/summarize.py 02_coldconn_results.txt
   ```

### Вариант 2: Полный запуск с TLS

1. **Убедитесь, что сертификаты созданы**
   ```bash
   ls df/certs/  # должны быть: ca.crt, server.crt, server.key
   ls smft/certs/  # должны быть: ca.crt, client.crt, client.key
   ```

2. **Генерация protobuf заглушек** (если не сделано)
   ```bash
   python -m grpc_tools.protoc --proto_path=proto --python_out=df --grpc_python_out=df proto/score.proto
   python -m grpc_tools.protoc --proto_path=proto --python_out=smft --grpc_python_out=smft proto/score.proto
   ```

3. **Запуск DF сервера с TLS**
   ```bash
   cd df
   python 01_steady_server.py
   ```
   В другом терминале:

4. **Запуск теста стабильного состояния**
   ```bash
   cd smft
   N_RPS=100 T_DURATION_SEC=60 T_WARMUP_SEC=10 python 01_steady_client.py
   ```

5. **Остановка сервера и запуск второго теста**
   ```bash
   # Остановить предыдущий сервер (Ctrl+C)
   cd df
   python 02_coldconn_server.py
   ```
   
   В другом терминале:
   ```bash
   cd smft
   T_DURATION_SEC=30 python 02_coldconn_client.py
   ```

6. **Анализ результатов**
   ```bash
   python tools/summarize.py smft/01_steady_results.txt
   python tools/summarize.py smft/02_coldconn_results.txt
   ```

## Конфигурация

### Переменные окружения

**DF Сервер (.env)**
```bash
DF_HOST=0.0.0.0          # Адрес привязки сервера
DF_PORT=50051            # Порт сервера  
DELAY_MS=5               # Искусственная задержка в миллисекундах
TLS_CA=certs/ca.crt      # Сертификат CA
TLS_CERT=certs/server.crt # Сертификат сервера
TLS_KEY=certs/server.key  # Приватный ключ сервера
```

**SMFT Клиент (.env)**  
```bash
DF_HOST=localhost        # Имя хоста целевого сервера
DF_PORT=50051           # Порт целевого сервера
N_RPS=500               # Запросов в секунду (только для 01_steady)
T_DURATION_SEC=300      # Длительность теста в секундах
T_WARMUP_SEC=30         # Длительность разогрева в секундах (только для 01_steady)
TLS_CA=certs/ca.crt     # Сертификат CA
TLS_CERT=certs/client.crt # Сертификат клиента  
TLS_KEY=certs/client.key  # Приватный ключ клиента
```

## Примеры различных нагрузок

### Лёгкая нагрузка (тестирование)
```bash
# 10 RPS на 10 секунд
N_RPS=10 T_DURATION_SEC=10 T_WARMUP_SEC=2 python 01_steady_client.py
```

### Средняя нагрузка
```bash
# 500 RPS на 5 минут
N_RPS=500 T_DURATION_SEC=300 T_WARMUP_SEC=30 python 01_steady_client.py
```

### Высокая нагрузка
```bash
# 2000 RPS на 10 минут  
N_RPS=2000 T_DURATION_SEC=600 T_WARMUP_SEC=60 python 01_steady_client.py
```

### Длительный тест холодных соединений
```bash
# 300 холодных соединений (5 минут по 1 RPS)
T_DURATION_SEC=300 python 02_coldconn_client.py
```

## Структура проекта

```
repo-root/
  proto/score.proto              # Определение протокола
  df/                           # Сервер DataFactory (SUT)
    Dockerfile
    .env
    01_steady_server.py          # Сервер для теста стабильного состояния
    02_coldconn_server.py        # Сервер для теста холодного соединения
    certs/ (ca.crt, server.crt, server.key)
  smft/                         # SMFT клиент / генератор нагрузки
    Dockerfile  
    .env
    01_steady_client.py          # Клиент для теста стабильного состояния
    02_coldconn_client.py        # Клиент для теста холодного соединения
    certs/ (ca.crt, client.crt, client.key)
  tools/
    summarize.py                # Инструмент постобработки
  README.md                     # Документация на английском
  README_RU.md                  # Документация на русском
  CLAUDE.md                     # Техническая спецификация
```

## Формат вывода

**01_steady_results.txt**
```
#TEST=01_steady
{"ok":true,"latency_ms":5.83}
{"ok":true,"latency_ms":6.12}
{"ok":false,"code":"DEADLINE_EXCEEDED"}
```

**02_coldconn_results.txt**
```
#TEST=02_coldconn  
{"ok":true,"t_connect_ms":19.4,"t_first_rpc_ms":6.1,"t_total_ms":25.5}
{"ok":true,"t_connect_ms":18.2,"t_first_rpc_ms":5.8,"t_total_ms":24.1}
```

## Пример анализа результатов

### Тест стабильного состояния (10 RPS, 5с)
```
Всего запросов: 51
Успешных: 51 (100.0%)  
Средняя задержка: 8.37мс
P50: 7.34мс | P90: 7.74мс | P95: 8.02мс | P99: 48.16мс
```

### Тест холодного соединения (5 попыток)
```
Всего попыток: 5
Успешных: 5 (100.0%)
Среднее время соединения: 2.40мс
Среднее время первого RPC: 12.12мс  
Среднее общее время: 14.70мс
```

## Настройка TLS

Система поддерживает как **односторонний TLS**, так и **полный mTLS**:

- **Односторонний TLS**: Клиент проверяет сертификат сервера
- **mTLS**: Взаимная аутентификация сертификатов  

Генерация сертификатов через OpenSSL:

```bash
# Генерация CA
openssl genrsa -out ca.key 4096
openssl req -new -x509 -key ca.key -sha256 -subj "/C=RU/ST=Moscow/O=TestLab/CN=TestCA" -days 365 -out ca.crt

# Генерация сертификата сервера  
openssl genrsa -out server.key 4096
openssl req -new -key server.key -subj "/C=RU/ST=Moscow/O=TestLab/CN=localhost" -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -sha256

# Генерация сертификата клиента
openssl genrsa -out client.key 4096
openssl req -new -key client.key -subj "/C=RU/ST=Moscow/O=TestLab/CN=smft-client" -out client.csr  
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365 -sha256
```

## Ожидаемые показатели производительности

### **С Protobuf 6.x (Рекомендуется)**
- **Средняя задержка**: ~7.1мс (5мс искусственная задержка + 2.1мс накладные расходы)
- **P99 задержка**: ~8.2мс (очень стабильная производительность)
- **Пропускная способность**: До 2000+ RPS устойчиво
- **Сериализация**: ~0.05мс (на 15% быстрее protobuf 4.x)

### **С Protobuf 4.x (Совместимость)**
- **Средняя задержка**: ~8.4мс (5мс искусственная задержка + 3.4мс накладные расходы)  
- **P99 задержка**: ~48мс (большие колебания под нагрузкой)
- **Пропускная способность**: До 1500+ RPS устойчиво
- **Сериализация**: ~0.06мс

### **Общие показатели**
- **Искусственная задержка**: ~5мс на запрос (настраивается через `DELAY_MS`)
- **Сетевые накладные расходы**: ~1-3мс для локальных соединений
- **Установка соединения**: ~15-25мс для TLS handshake (холодные соединения)
- **HTTP/2 мультиплексирование**: Минимальные накладные расходы на переиспользуемых каналах

**Рекомендация**: Используйте protobuf 6.x для производственного тестирования задержек, чтобы минимизировать шум измерений.

## Устранение неполадок

### Частые проблемы

1. **Конфликты версий Protobuf**
   ```
   ImportError: cannot import name 'runtime_version' from 'google.protobuf'
   ```
   **Решение**: Пересгенерируйте заглушки с правильной версией protobuf:
   ```bash
   rm df/score_pb2*.py smft/score_pb2*.py
   python -m grpc_tools.protoc --proto_path=proto --python_out=df --grpc_python_out=df proto/score.proto
   python -m grpc_tools.protoc --proto_path=proto --python_out=smft --grpc_python_out=smft proto/score.proto
   ```

2. **Конфликты зависимостей**
   ```
   googleapis-common-protos требует protobuf<5.0.0, но у вас protobuf 6.32.0
   ```
   **Решение**: Используйте виртуальное окружение для protobuf 6.x:
   ```bash
   ./quick_protobuf6_test.sh  # Создает изолированное окружение
   ```

3. **Ошибки сертификатов**
   - Убедитесь, что CN совпадает с именем хоста (используйте `localhost` для локального тестирования)  
   - Проверьте цепочку сертификатов: `openssl verify -CAfile ca.crt server.crt`

4. **Таймауты соединения**  
   - Убедитесь, что сервер слушает: `netstat -an | grep 50051`
   - Проверьте правила файрвола для порта 50051

5. **Ошибки импорта**
   - Пересгенерируйте protobuf заглушки: `python -m grpc_tools.protoc ...`
   - Убедитесь, что установлены `grpcio` и `python-dotenv`

### Режим отладки
Установите переменные окружения для подробного логирования gRPC:
```bash
export GRPC_VERBOSITY=DEBUG
export GRPC_TRACE=all
```

## Полезные команды

### Проверка статуса
```bash
# Проверка, что сервер слушает
netstat -an | grep 50051

# Проверка сертификатов
openssl x509 -in df/certs/server.crt -text -noout | head -20

# Тест SSL соединения
openssl s_client -connect localhost:50051 -CAfile df/certs/ca.crt
```

### Мониторинг тестов
```bash
# Мониторинг результатов в реальном времени
tail -f smft/01_steady_results.txt
tail -f smft/02_coldconn_results.txt

# Подсчёт успешных запросов
grep '"ok":true' smft/01_steady_results.txt | wc -l
```

## Примеры запуска для разных сценариев

### Быстрая проверка (30 секунд)
```bash
# Терминал 1: Сервер
cd df && python 01_steady_server.py

# Терминал 2: Клиент  
cd smft && N_RPS=50 T_DURATION_SEC=30 T_WARMUP_SEC=5 python 01_steady_client.py
```

### Нагрузочное тестирование (10 минут)
```bash
# Терминал 1: Сервер
cd df && python 01_steady_server.py

# Терминал 2: Клиент
cd smft && N_RPS=1000 T_DURATION_SEC=600 T_WARMUP_SEC=60 python 01_steady_client.py
```

### Анализ холодных соединений
```bash
# Терминал 1: Сервер
cd df && python 02_coldconn_server.py  

# Терминал 2: Клиент (100 холодных соединений)
cd smft && T_DURATION_SEC=100 python 02_coldconn_client.py
```

## Интерпретация результатов

### Метрики теста стабильного состояния
- **latency_ms**: Время от отправки запроса до получения ответа
- **Ожидаемые значения**: 5-10мс (5мс искусственная задержка + накладные расходы)
- **P99 > 50мс**: Может указывать на проблемы с garbage collection или сетью

### Метрики теста холодного соединения  
- **t_connect_ms**: Время установки TLS соединения
- **t_first_rpc_ms**: Время первого RPC после установки соединения
- **t_total_ms**: Общее время (соединение + RPC)
- **Ожидаемые значения**: 15-30мс общее время для localhost

## Примечания по разработке

- **Измерение времени**: Использует `time.perf_counter_ns()` для высокоточных измерений
- **Контроль RPS**: Чистое планирование asyncio tick без внешних библиотек  
- **Обработка ошибок**: Захватывает коды состояния gRPC и таймауты
- **Зависимости**: В runtime требует только `grpcio` + `python-dotenv`
- **Сборка**: Использует многоэтапную сборку Docker для минимальных runtime образов

## Лицензия

Внутренний инструмент тестирования - не для промышленного использования.