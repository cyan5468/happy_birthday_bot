# 誕生日お祝いbot

指定されたDiscordサーバー内で誕生日を登録し、設定されたチャンネルと時刻に自動でお祝いメッセージを通知するBotです。

## 主な機能 (Main Features)

* **誕生日登録/更新:** 名前、誕生日(MM/DD形式)、任意でメンション対象ユーザーを指定して登録・更新できます。同じ名前が登録された場合は上書きされます。
* **誕生日一覧表示:** サーバーに登録されている誕生日情報を一覧で表示します。メンション対象も確認できます。
* **誕生日削除:** 登録されている誕生日情報を名前で削除します。
* **メンション設定変更:** 登録済みの名前に対して、誕生日通知時にメンションするユーザーを設定、またはメンションを無効化します。
* **メンション設定確認:** 指定した名前のメンション設定状況を確認します。
* **通知チャンネル設定:** 誕生日通知メッセージを送信するチャンネルを設定します。
* **通知時刻設定:** 誕生日通知を行う時刻を設定します。タイムゾーン（UTCオフセット）も任意で指定可能です（デフォルトは日本時間 JST/UTC+9.0）。
* **通知メッセージ設定:** 誕生日通知メッセージのテンプレートをカスタマイズできます (`<name>` プレースホルダー対応)。
* **設定確認:** 現在設定されている通知チャンネル、通知時刻（ローカルタイムとUTC）、**通知メッセージテンプレート**を確認します。
* **自動通知:** 設定された時刻になると、その日に誕生日を迎える人のリストを通知チャンネルへ自動投稿します（メンション設定・カスタムメッセージに基づき通知）。

## 技術スタック (Technology Stack)

* Python 3.8+
* discord.py (v2.x)
* python-dotenv
* SQLite3

## 前提条件 (Prerequisites)

* Python 3.8 以上がインストールされている環境
* Discord Bot アプリケーションの作成とBotトークンの取得
    * [Discord Developer Portal](https://discord.com/developers/applications/) で作成します。
* **Privileged Gateway Intents の有効化:**
    * Discord Developer Portal の Bot 設定ページで、以下の Intent を**必ず有効**にしてください。
        * `SERVER MEMBERS INTENT`
        * `MESSAGE CONTENT INTENT`

## セットアップ手順 (Setup Instructions)

1.  **リポジトリのクローン (任意):**
    ```bash
    git clone <リポジトリURL>
    cd <リポジトリ名>
    ```
    または、ソースコード (`.py` ファイルなど) を直接ダウンロードして任意のディレクトリに配置します。

2.  **Python仮想環境の作成と有効化 (推奨):**
    ```bash
    python3 -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS / Linux
    source venv/bin/activate
    ```

3.  **依存ライブラリのインストール:**
    ```bash
    pip install discord.py python-dotenv
    ```

4.  **`.env` ファイルの作成と編集:**
    * Botのソースコードと同じディレクトリに `.env` という名前のファイルを作成します。
    * 以下の内容を記述し、`<あなたのBotトークン>` を実際のトークンに置き換えます。
        ```dotenv
        DISCORD_TOKEN=<あなたのBotトークン>
        ```

5.  **Privileged Intents の有効化 (再確認):**
    * Discord Developer Portal で、Botの `SERVER MEMBERS INTENT` と `MESSAGE CONTENT INTENT` が有効になっていることを確認してください。

## データベース (Database)

* このBotは、誕生日情報やサーバー設定を保存するために **SQLite** を使用します。
* データベースファイル (`birthdays.db`) は、Botの初回起動時にスクリプトと同じディレクトリに自動的に作成されます。
* **注意:** このデータベースファイルにはユーザーデータが含まれるため、**このファイルは絶対に公開しないでください。**

## Botの起動 (Running the Bot)

1.  **直接実行 (テスト用):**
    ```bash
    # 仮想環境を有効化してから実行
    # your_bot_script_name.py は実際のファイル名に置き換えてください
    python3 your_bot_script_name.py
    ```
    ターミナルを閉じるとBotも停止します。

2.  **常時稼働 (推奨):**
    * サーバー (VPSなど) で24時間稼働させる場合は、`systemd` (Linux) や `supervisor` などのプロセス管理ツールを使用することを強く推奨します。これにより、Botがクラッシュした場合の自動再起動や、バックグラウンドでの実行が可能になります。
    * (参考: `systemd` の設定例などは、ホスティングガイドを参照してください)

## コマンド一覧 (Command List)

Botの操作はスラッシュコマンド (`/`) で行います。

* **`/register_birthday name:<名前> birthday:<誕生日(MM/DD)> [user:<メンション対象>]`**
    * 誕生日を登録または更新します。
    * `name`: 登録する名前 (サーバー内で一意)。
    * `birthday`: `MM/DD` 形式 (例: `04/01`)。
    * `user` (任意): 通知時にメンションしたいDiscordユーザーを指定します。指定しない場合はメンションされません。
    * 確認メッセージではメンション対象は **表示名** で表示され、即時メンションは飛びません。

* **`/list_birthdays`**
    * このサーバーに登録されている全ての誕生日を一覧表示します。

* **`/delete_birthday name:<名前>`**
    * 指定した名前の誕生日情報を削除します。

* **`/set_mention name:<名前> [mention_target:<メンション対象>]`**
    * 指定した名前の誕生日通知時のメンション設定を変更します。
    * `mention_target` (任意): メンションしたいユーザーを指定すると有効化、指定しないと無効化されます。
    * 確認メッセージではメンション対象は **表示名** で表示され、即時メンションは飛びません。

* **`/check_mention name:<名前>`**
    * 指定した名前の現在のメンション設定状況を確認します。

* **`/set_announce_channel channel:<チャンネル>`**
    * 誕生日通知メッセージを送信するテキストチャンネルを設定します。
    * 実行には「サーバー管理」権限が必要です。

* **`/set_announce_time hour:<時> minute:<分> [utc_offset:<オフセット>]`**
    * 誕生日通知を行う時刻を設定します。
    * `hour`: 0-23の範囲で指定。
    * `minute`: 0-59の範囲で指定。
    * `utc_offset` (任意): UTCからの時差を数値で指定 (-12.0 ~ +14.0)。例: 日本時間なら `9.0`。省略した場合はデフォルト (JST: UTC+9.0) になります。
    * 実行には「サーバー管理」権限が必要です。
    * 先に `/set_announce_channel` でチャンネル設定が必要です。

* **`/set_announce_message template:<テンプレート>`**
    * 誕生日通知メッセージのテンプレートを設定します。
    * `template`: メッセージのテンプレート文字列。テンプレート内で `<name>` と記述すると、その部分が実際の誕生者の名前（太字のリスト形式）に置き換わります。
    * 例: `template:「🎂 <name>さん、お誕生日おめでとうございます！ 🥳」`
    * 実行には「サーバー管理」権限が必要です。
    * 先に `/set_announce_channel` でチャンネル設定が必要です。

* **`/check_settings`**
    * 現在設定されている通知チャンネル、通知時刻（設定されたローカルタイムとUTC）、および**通知メッセージテンプレート**を確認します。テンプレートが設定されていない場合はデフォルトのテンプレートが表示されます。

## 注意事項 (Notes)

* `.env` ファイル（Botトークン）と `birthdays.db` ファイル（ユーザーデータ）は、セキュリティとプライバシー保護のため、**このファイルは絶対に公開しないでください。**
* Botを安定稼働させるためには、適切なホスティング環境とプロセス管理が必要です。

