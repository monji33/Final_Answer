# 課題2 Docker & DB

## 構成

- OS: Ubuntu 20.04
- Python: Python 3.8
- DB: MySQL 8.0
- Database: ex2
- Table: ex2_2

## 使用ライブラリ

- sqlalchemy
- pandas
- requests
- pymysql
- beautifulsoup4
- cryptography
- re（Python標準ライブラリ）

## 実行手順

### 1. Dockerイメージをクリーンビルド

```bash
docker compose down
docker compose build --no-cache