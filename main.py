import discord
from discord.ext import tasks, commands
import datetime
import os
from dotenv import load_dotenv
import sqlite3
from discord import app_commands # スラッシュコマンド用
from typing import List, Optional
import logging

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    logger.critical("DISCORD_TOKEN が .env ファイルに見つかりません。")
    exit()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

DB_NAME = 'birthdays.db'
DEFAULT_ANNOUNCE_HOUR_UTC = 0 # デフォルト通知時刻 (UTC)
DEFAULT_ANNOUNCE_MINUTE_UTC = 0 # デフォルト通知時刻 (UTC)
DEFAULT_TIMEZONE_OFFSET = 9.0 # デフォルトのタイムゾーンオフセット (JST)
# デフォルトの通知メッセージテンプレート
DEFAULT_ANNOUNCE_MESSAGE = "🎉 今日 {today_date} は {names} さんの誕生日です！おめでとうございます！ {mentions}"

# --- データベース関連関数 ---

def get_db_connection():
    """データベース接続を取得する関数"""
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        logger.debug("データベース接続成功")
        return conn
    except sqlite3.Error as e:
        logger.error(f"データベース接続エラー: {e}")
        return None

def setup_database():
    """データベースのセットアップを行う関数"""
    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            return False
        cursor = conn.cursor()

        # birthdays テーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS birthdays (
                guild_id INTEGER NOT NULL, display_name TEXT NOT NULL COLLATE NOCASE, birthday TEXT NOT NULL,
                mention_user_id INTEGER, registered_by_user_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, display_name) ) ''')
        logger.info("birthdays テーブルを確認/作成しました。")
        cursor.execute("PRAGMA table_info(birthdays)")
        columns_b = [column['name'] for column in cursor.fetchall()]
        if "mention_user_id" not in columns_b:
            cursor.execute("ALTER TABLE birthdays ADD COLUMN mention_user_id INTEGER")
            logger.info("birthdays テーブルに mention_user_id カラムを追加しました。")
        if "registered_by_user_id" not in columns_b:
            if "registered_user_id" in columns_b:
                cursor.execute("ALTER TABLE birthdays RENAME COLUMN registered_user_id TO registered_by_user_id")
                logger.info("birthdays テーブルの registered_user_id を registered_by_user_id に変更しました。")
            else:
                cursor.execute("ALTER TABLE birthdays ADD COLUMN registered_by_user_id INTEGER")
                logger.info("birthdays テーブルに registered_by_user_id カラムを追加しました。")

        # server_settings テーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS server_settings (
                guild_id INTEGER PRIMARY KEY, announce_channel_id INTEGER NOT NULL,
                announce_hour_utc INTEGER, announce_minute_utc INTEGER,
                announce_timezone_offset REAL,
                announce_message_template TEXT
            ) ''')
        logger.info("server_settings テーブルを確認/作成しました。")
        cursor.execute("PRAGMA table_info(server_settings)")
        columns_s = {column['name']: column['type'] for column in cursor.fetchall()}
        if "announce_hour_utc" not in columns_s:
            cursor.execute("ALTER TABLE server_settings ADD COLUMN announce_hour_utc INTEGER")
            logger.info("server_settings テーブルに announce_hour_utc カラムを追加しました。")
        if "announce_minute_utc" not in columns_s:
            cursor.execute("ALTER TABLE server_settings ADD COLUMN announce_minute_utc INTEGER")
            logger.info("server_settings テーブルに announce_minute_utc カラムを追加しました。")
        if "announce_timezone_offset" not in columns_s:
            cursor.execute("ALTER TABLE server_settings ADD COLUMN announce_timezone_offset REAL")
            logger.info("server_settings テーブルに announce_timezone_offset カラムを追加しました。")
        if "announce_message_template" not in columns_s:
            cursor.execute("ALTER TABLE server_settings ADD COLUMN announce_message_template TEXT")
            logger.info("server_settings テーブルに announce_message_template カラムを追加しました。")

        conn.commit()
        logger.info("データベースのセットアップが正常に完了しました。")
        return True

    except sqlite3.Error as e:
        logger.error(f"データベースセットアップ中のエラー: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# --- ヘルパー関数 ---
def convert_local_to_utc(hour_local: int, minute_local: int, offset_hours: float) -> tuple[int, int]:
    """指定されたローカル時刻とオフセットをUTC時刻に変換する"""
    try:
        tz_local = datetime.timezone(datetime.timedelta(hours=offset_hours))
        now_dummy = datetime.datetime.now()
        dt_local = datetime.datetime(now_dummy.year, now_dummy.month, now_dummy.day, hour_local, minute_local, tzinfo=tz_local)
        dt_utc = dt_local.astimezone(datetime.timezone.utc)
        return dt_utc.hour, dt_utc.minute
    except ValueError:
        logger.error(f"ローカル時刻からUTCへの変換に失敗: hour={hour_local}, min={minute_local}, offset={offset_hours}")
        return 0, 0

def convert_utc_to_local_str(hour_utc: Optional[int], minute_utc: Optional[int], offset_hours: Optional[float]) -> str:
    """UTC時刻を指定されたオフセットのローカル時刻文字列 (HH:MM) に変換する"""
    if offset_hours is None:
        offset_hours = DEFAULT_TIMEZONE_OFFSET
    if hour_utc is None or minute_utc is None:
        hour_utc = DEFAULT_ANNOUNCE_HOUR_UTC
        minute_utc = DEFAULT_ANNOUNCE_MINUTE_UTC
    try:
        tz_local = datetime.timezone(datetime.timedelta(hours=offset_hours))
        now_dummy = datetime.datetime.now()
        dt_utc = datetime.datetime(now_dummy.year, now_dummy.month, now_dummy.day, hour_utc, minute_utc, tzinfo=datetime.timezone.utc)
        dt_local = dt_utc.astimezone(tz_local)
        return dt_local.strftime("%H:%M")
    except ValueError:
        logger.error(f"UTCからローカル時刻文字列への変換に失敗: hour={hour_utc}, min={minute_utc}, offset={offset_hours}")
        return "不明"

def format_offset(offset: Optional[float]) -> str:
    """UTCオフセットを文字列 (例: UTC+9.0) にフォーマットする"""
    if offset is None:
        offset = DEFAULT_TIMEZONE_OFFSET
    sign = "+" if offset >= 0 else "-"
    abs_offset = abs(offset)
    return f"UTC{sign}{abs_offset}"

# --- Botイベント ---

@bot.event
async def on_ready():
    logger.info(f'{bot.user} が起動しました')
    if not setup_database():
        logger.critical("データベースのセットアップに失敗しました。Botを停止します。")
        await bot.close()
        return
    conn_check = get_db_connection()
    if conn_check:
        conn_check.close()
        birthday_announce.start()
        logger.info("誕生日通知タスクを開始しました。")
    else:
        logger.error("誕生日通知タスク開始前にデータベース接続を確認できませんでした。")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logger.error(f"コマンド同期エラー: {e}")

# --- スラッシュコマンド ---

@bot.tree.command(name='set_announce_channel', description='誕生日をお知らせするチャンネルを設定します')
@app_commands.describe(channel='通知を送信するテキストチャンネル')
@app_commands.checks.has_permissions(manage_guild=True)
async def set_announce_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """誕生日通知チャンネルを設定するコマンド"""
    guild_id = interaction.guild_id
    announce_channel_id = channel.id
    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()
        # 既存の設定を維持
        cursor.execute("SELECT announce_hour_utc, announce_minute_utc, announce_timezone_offset, announce_message_template FROM server_settings WHERE guild_id = ?", (guild_id,))
        current_settings = cursor.fetchone()
        hour_utc = current_settings['announce_hour_utc'] if current_settings else None
        minute_utc = current_settings['announce_minute_utc'] if current_settings else None
        offset = current_settings['announce_timezone_offset'] if current_settings else None
        template = current_settings['announce_message_template'] if current_settings else None
        cursor.execute(
            """
            INSERT OR REPLACE INTO server_settings
            (guild_id, announce_channel_id, announce_hour_utc, announce_minute_utc, announce_timezone_offset, announce_message_template)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, announce_channel_id, hour_utc, minute_utc, offset, template), )
        conn.commit()
        logger.info(f'サーバー {interaction.guild.name} (ID: {guild_id}) の通知チャンネルを {channel.name} (ID: {announce_channel_id}) に設定しました。')
        await interaction.response.send_message(f'誕生日をお知らせするチャンネルを {channel.mention} に設定しました。')
    except sqlite3.Error as e:
        logger.error(f"set_announce_channel コマンドエラー (Guild: {guild_id}): {e}")
        if conn:
            conn.rollback()
        await interaction.response.send_message("データベースエラーが発生しました。設定を保存できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()

@bot.tree.command(name='set_announce_time', description='誕生日をお知らせする時刻とタイムゾーンを設定します')
@app_commands.describe( hour='通知時刻 (時, 0-23)', minute='通知時刻 (分, 0-59)', utc_offset=f'UTCからの時差 (-12.0 ~ +14.0)。例: JSTなら9.0。省略時: {DEFAULT_TIMEZONE_OFFSET:+}')
@app_commands.checks.has_permissions(manage_guild=True)
async def set_announce_time(interaction: discord.Interaction, hour: app_commands.Range[int, 0, 23], minute: app_commands.Range[int, 0, 59], utc_offset: Optional[app_commands.Range[float, -12.0, 14.0]] = None):
    """誕生日通知時刻を設定するコマンド"""
    guild_id = interaction.guild_id
    effective_offset = utc_offset if utc_offset is not None else DEFAULT_TIMEZONE_OFFSET
    hour_utc, minute_utc = convert_local_to_utc(hour, minute, effective_offset)
    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()
        # 既存のチャンネル・メッセージ設定を維持
        cursor.execute("SELECT announce_channel_id, announce_message_template FROM server_settings WHERE guild_id = ?", (guild_id,))
        current_settings = cursor.fetchone()
        if not current_settings or not current_settings['announce_channel_id']:
            await interaction.response.send_message("先に `/set_announce_channel` で通知チャンネルを設定してください。", ephemeral=True)
            return
        announce_channel_id = current_settings['announce_channel_id']
        template = current_settings['announce_message_template'] if current_settings else None
        cursor.execute(
            """
            INSERT OR REPLACE INTO server_settings
            (guild_id, announce_channel_id, announce_hour_utc, announce_minute_utc, announce_timezone_offset, announce_message_template)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, announce_channel_id, hour_utc, minute_utc, effective_offset, template), )
        conn.commit()
        local_time_str = f"{hour:02}:{minute:02}"
        timezone_str = format_offset(effective_offset)
        utc_time_str = f"{hour_utc:02}:{minute_utc:02} UTC"
        logger.info(f'サーバー {interaction.guild.name} (ID: {guild_id}) の通知時刻を {local_time_str} ({timezone_str}) / {utc_time_str} に設定しました。')
        await interaction.response.send_message(f'誕生日をお知らせする時刻を **{local_time_str} ({timezone_str})** ({utc_time_str}) に設定しました。')
    except sqlite3.Error as e:
        logger.error(f"set_announce_time コマンドエラー (Guild: {guild_id}): {e}")
        if conn:
            conn.rollback()
        await interaction.response.send_message("データベースエラーが発生しました。時刻を設定できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()

@bot.tree.command(name='set_announce_message', description='誕生日通知メッセージのテンプレートを設定します (<name>で名前が入ります)')
@app_commands.describe(template='メッセージテンプレート文字列。例:「今日は<name>さんの誕生日！🎉」')
@app_commands.checks.has_permissions(manage_guild=True)
async def set_announce_message(interaction: discord.Interaction, template: str):
    """誕生日通知メッセージのテンプレートを設定するコマンド"""
    guild_id = interaction.guild_id

    if len(template) > 1000:
        await interaction.response.send_message("メッセージテンプレートが長すぎます。1000文字以内で設定してください。", ephemeral=True)
        return

    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()

        # 既存のチャンネル・時刻・オフセット設定を維持
        cursor.execute("SELECT announce_channel_id, announce_hour_utc, announce_minute_utc, announce_timezone_offset FROM server_settings WHERE guild_id = ?", (guild_id,))
        current_settings = cursor.fetchone()
        if not current_settings or not current_settings['announce_channel_id']:
            await interaction.response.send_message("先に `/set_announce_channel` で通知チャンネルを設定してください。", ephemeral=True)
            return
        announce_channel_id = current_settings['announce_channel_id']
        hour_utc = current_settings['announce_hour_utc']
        minute_utc = current_settings['announce_minute_utc']
        offset = current_settings['announce_timezone_offset']

        # メッセージテンプレートを更新
        cursor.execute(
            """
            INSERT OR REPLACE INTO server_settings
            (guild_id, announce_channel_id, announce_hour_utc, announce_minute_utc, announce_timezone_offset, announce_message_template)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, announce_channel_id, hour_utc, minute_utc, offset, template), )
        conn.commit()

        logger.info(f'サーバー {interaction.guild.name} (ID: {guild_id}) の通知メッセージテンプレートを設定しました: {template}')
        embed = discord.Embed(title="通知メッセージテンプレート設定完了", description=f"以下のテンプレートを設定しました。\n`<name>`の部分は実際の誕生者の名前に置き換わります。", color=discord.Color.green())
        embed.add_field(name="設定されたテンプレート", value=f"```{template}```", inline=False)
        await interaction.response.send_message(embed=embed)

    except sqlite3.Error as e:
        logger.error(f"set_announce_message コマンドエラー (Guild: {guild_id}): {e}")
        if conn:
            conn.rollback()
        await interaction.response.send_message("データベースエラーが発生しました。メッセージテンプレートを設定できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()


@bot.tree.command(name="check_settings", description="現在の通知チャンネル・時刻・メッセージの設定を確認します。")
async def check_settings(interaction: discord.Interaction):
    """現在の通知設定を確認するコマンド"""
    guild_id = interaction.guild_id
    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()
        cursor.execute('SELECT announce_channel_id, announce_hour_utc, announce_minute_utc, announce_timezone_offset, announce_message_template FROM server_settings WHERE guild_id = ?', (guild_id,))
        settings = cursor.fetchone()
        if not settings or not settings['announce_channel_id']:
            await interaction.response.send_message("通知チャンネルが設定されていません。 `/set_announce_channel` で設定してください。", ephemeral=True)
            return

        channel_id = settings['announce_channel_id']
        hour_utc = settings['announce_hour_utc']
        minute_utc = settings['announce_minute_utc']
        offset = settings['announce_timezone_offset']
        message_template = settings['announce_message_template']

        channel = bot.get_channel(channel_id) or (interaction.guild and interaction.guild.get_channel(channel_id))
        channel_mention = channel.mention if channel else f"不明なチャンネル (ID: {channel_id})"

        local_time_str = convert_utc_to_local_str(hour_utc, minute_utc, offset)
        timezone_str = format_offset(offset)
        utc_hour_for_display = hour_utc if hour_utc is not None else DEFAULT_ANNOUNCE_HOUR_UTC
        utc_minute_for_display = minute_utc if minute_utc is not None else DEFAULT_ANNOUNCE_MINUTE_UTC
        utc_time_str = f"{utc_hour_for_display:02}:{utc_minute_for_display:02} UTC"
        time_info = f"通知時刻: **{local_time_str} ({timezone_str})** ({utc_time_str})"
        if offset is None and (hour_utc is None or minute_utc is None):
            time_info += " (デフォルト)"

        if message_template:
            template_info = f"通知メッセージ:\n```\n{message_template}\n```"
        else:
            default_display = DEFAULT_ANNOUNCE_MESSAGE.replace("{today_date}", "日付").replace("{names}", "<名前>").replace("{mentions}", "[メンション]")
            template_info = f"通知メッセージ: デフォルト\n```\n{default_display}\n```"

        message = f"現在の設定:\n- 通知チャンネル: {channel_mention}\n- {time_info}\n- {template_info}"
        await interaction.response.send_message(message, ephemeral=True)

    except sqlite3.Error as e:
        logger.error(f"check_settings コマンドエラー (Guild: {guild_id}): {e}")
        await interaction.response.send_message("データベースエラーが発生しました。設定を確認できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()


@bot.tree.command(name='register_birthday', description='名前と誕生日を指定して登録・上書きします')
@app_commands.describe( name='登録する人の名前 (サーバー内で一意)', birthday='誕生日 (MM/DD形式、例: 01/23)', user='(任意) 誕生日通知でメンションするDiscordユーザー' )
async def register_birthday(interaction: discord.Interaction, name: str, birthday: str, user: Optional[discord.User] = None):
    """誕生日を登録・上書きするコマンド"""
    guild_id = interaction.guild_id
    registered_by_user_id = interaction.user.id
    mention_user_id = user.id if user else None
    try:
        birthday_date = datetime.datetime.strptime(birthday, '%m/%d').strftime('%m/%d')
    except ValueError:
        await interaction.response.send_message('誕生日の形式が正しくありません。MM/DD (例: 04/01) で入力してください。', ephemeral=True)
        return

    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM birthdays WHERE guild_id = ? AND display_name = ?", (guild_id, name))
        exists = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO birthdays (guild_id, display_name, birthday, mention_user_id, registered_by_user_id)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id, display_name) DO UPDATE SET
            birthday = excluded.birthday, mention_user_id = excluded.mention_user_id, registered_by_user_id = excluded.registered_by_user_id
            """,
            (guild_id, name, birthday_date, mention_user_id, registered_by_user_id)
        )
        conn.commit()

        action_text = "更新" if exists else "登録"
        if user:
            user_display = discord.utils.escape_markdown(user.display_name)
            mention_text = f" (メンション対象: **{user_display}** さん)"
        else:
            mention_text = " (メンションなし)"

        log_mention_id = f"メンションID: {mention_user_id}" if mention_user_id else "メンションなし"
        logger.info(f"サーバー {interaction.guild.name} (ID: {guild_id}) で誕生日{action_text}: {name} ({birthday_date}), {log_mention_id}, 登録者ID: {registered_by_user_id}")
        await interaction.response.send_message(f'`{name}` さんの誕生日 ({birthday_date}) を{action_text}しました！{mention_text}', ephemeral=False)

    except sqlite3.Error as e:
        logger.error(f"register_birthday コマンドエラー (Guild: {guild_id}, Name: {name}): {e}")
        if conn:
            conn.rollback()
        await interaction.response.send_message("データベースエラーが発生しました。登録・更新できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()

@bot.tree.command(name='list_birthdays', description='このサーバーに登録されている誕生日の一覧を表示します')
async def list_birthdays(interaction: discord.Interaction):
    """登録されている誕生日を一覧表示するコマンド"""
    guild_id = interaction.guild_id
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("サーバー情報を取得できませんでした。", ephemeral=True)
        return
    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()
        cursor.execute('SELECT display_name, birthday, mention_user_id FROM birthdays WHERE guild_id = ? ORDER BY birthday, display_name', (guild_id,))
        results = cursor.fetchall()
        if not results:
            await interaction.response.send_message('まだ誰も誕生日を登録していません。 `/register_birthday` で登録しましょう！', ephemeral=True)
            return
        embed = discord.Embed(title=f'{guild.name} の誕生日一覧', color=discord.Color.blue())
        description_lines = []
        for row in results:
            name = row['display_name']
            birthday = row['birthday']
            mention_user_id = row['mention_user_id']
            mention_str = ""
            if mention_user_id:
                member = guild.get_member(mention_user_id)
                if member:
                    mention_str = f" ({member.mention})"
                else:
                    user = bot.get_user(mention_user_id)
                    mention_str = f" ({user.name} - サーバーにいません)" if user else f" (ID: {mention_user_id} - 不明なユーザー)"
            else:
                mention_str = " (メンションなし)"
            description_lines.append(f"**{name}**: {birthday}{mention_str}")
        full_description = "\n".join(description_lines)
        if len(full_description) > 4000:
            await interaction.response.send_message("登録数が多すぎるため、一部のみ表示します。（将来的にページネーション対応予定）")
            embed.description = full_description[:4000] + "\n..."
        else:
            embed.description = full_description
        await interaction.response.send_message(embed=embed)
    except sqlite3.Error as e:
        logger.error(f"list_birthdays コマンドエラー (Guild: {guild_id}): {e}")
        await interaction.response.send_message("データベースエラーが発生しました。一覧を表示できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()

@bot.tree.command(name="check_mention", description="指定した名前の人のメンション設定を確認します。")
@app_commands.describe(name='確認する人の名前')
async def check_mention(interaction: discord.Interaction, name: str):
    """指定した名前のメンション設定を確認するコマンド"""
    guild_id = interaction.guild_id
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("サーバー情報を取得できませんでした。", ephemeral=True)
        return
    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()
        cursor.execute('SELECT mention_user_id FROM birthdays WHERE guild_id = ? AND display_name = ?', (guild_id, name))
        result = cursor.fetchone()
        if not result:
            await interaction.response.send_message(f'`{name}` さんの誕生日は登録されていません。', ephemeral=True)
            return
        mention_user_id = result['mention_user_id']
        if mention_user_id:
            member = guild.get_member(mention_user_id)
            if member:
                message = f'`{name}` さんの誕生日は `{member.mention}` にメンションされる設定です。'
            else:
                user = bot.get_user(mention_user_id)
                message = f'`{name}` さんの誕生日は `{user.name}` (ID: {mention_user_id}, サーバーにいません) にメンションされる設定です。' if user else f'`{name}` さんの誕生日は 不明なユーザー (ID: {mention_user_id}) にメンションされる設定です。'
        else:
            message = f'`{name}` さんの誕生日はメンションされない設定です。'
        await interaction.response.send_message(message, ephemeral=True)
    except sqlite3.Error as e:
        logger.error(f"check_mention コマンドエラー (Guild: {guild_id}, Name: {name}): {e}")
        await interaction.response.send_message("データベースエラーが発生しました。確認できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()

@bot.tree.command(name="set_mention", description="指定した名前の人のメンション設定を変更します。")
@app_commands.describe( name='設定を変更する人の名前', mention_target='(任意) メンションを有効にする場合、対象ユーザーを指定。指定しない場合はメンション無効化。')
async def set_mention(interaction: discord.Interaction, name: str, mention_target: Optional[discord.User] = None):
    """指定した名前のメンション設定を変更するコマンド"""
    guild_id = interaction.guild_id
    new_mention_user_id = mention_target.id if mention_target else None
    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM birthdays WHERE guild_id = ? AND display_name = ?", (guild_id, name))
        exists = cursor.fetchone()
        if not exists:
            await interaction.response.send_message(f'`{name}` さんの誕生日は登録されていません。まず `/register_birthday` で登録してください。', ephemeral=True)
            return
        cursor.execute( 'UPDATE birthdays SET mention_user_id = ? WHERE guild_id = ? AND display_name = ?', (new_mention_user_id, guild_id, name) )
        conn.commit()

        if mention_target:
            mention_target_display = discord.utils.escape_markdown(mention_target.display_name)
            message = f'`{name}` さんの誕生日通知メンションを **{mention_target_display}** さんに設定しました。'
            log_message = f"メンションを有効化 (対象: {mention_target.name}#{mention_target.discriminator}, ID: {new_mention_user_id})"
        else:
            message = f'`{name}` さんの誕生日通知メンションを無効化しました。'
            log_message = "メンションを無効化"

        logger.info(f"サーバー {interaction.guild.name} (ID: {guild_id}) でメンション設定変更: {name} - {log_message}")
        await interaction.response.send_message(message, ephemeral=False)

    except sqlite3.Error as e:
        logger.error(f"set_mention コマンドエラー (Guild: {guild_id}, Name: {name}): {e}")
        if conn:
            conn.rollback()
        await interaction.response.send_message("データベースエラーが発生しました。設定を変更できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()

@bot.tree.command(name="delete_birthday", description="登録した誕生日を名前で削除します。")
@app_commands.describe(name='削除する誕生日情報の名前')
async def delete_birthday(interaction: discord.Interaction, name: str):
    """名前を指定して誕生日情報を削除するコマンド"""
    guild_id = interaction.guild_id
    conn = None
    try:
        conn = get_db_connection()
        if conn is None:
            await interaction.response.send_message("データベース接続に失敗しました。", ephemeral=True)
            return
        cursor = conn.cursor()
        cursor.execute( 'DELETE FROM birthdays WHERE guild_id = ? AND display_name = ?', (guild_id, name), )
        deleted_rows = cursor.rowcount
        conn.commit()
        if deleted_rows > 0:
            logger.info(f"サーバー {interaction.guild.name} (ID: {guild_id}) で誕生日削除: {name}")
            await interaction.response.send_message(f'`{name}` さんの誕生日情報を削除しました！', ephemeral=True)
        else:
            await interaction.response.send_message(f'`{name}` さんの誕生日は登録されていません。', ephemeral=True)
    except sqlite3.Error as e:
        logger.error(f"delete_birthday コマンドエラー (Guild: {guild_id}, Name: {name}): {e}")
        if conn:
            conn.rollback()
        await interaction.response.send_message("データベースエラーが発生しました。削除できませんでした。", ephemeral=True)
    finally:
        if conn:
            conn.close()

# --- 定期実行タスク ---

@tasks.loop(minutes=1)
async def birthday_announce():
    """毎分実行し、設定された時刻になったサーバーの誕生日を確認・通知するタスク"""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    current_hour_utc = now_utc.hour
    current_minute_utc = now_utc.minute
    loop_interval_minutes = 1

    jst = datetime.timezone(datetime.timedelta(hours=9))
    today_jst_str = datetime.datetime.now(jst).strftime('%m/%d')
    logger.debug(f"誕生日通知タスク実行チェック: {now_utc.strftime('%Y-%m-%d %H:%M')} UTC")
    conn = None
    processed_guilds = set()
    try:
        conn = get_db_connection()
        if conn is None:
            logger.error("誕生日通知タスク: データベースに接続できません。")
            return
        cursor = conn.cursor()
        cursor.execute('SELECT guild_id, announce_channel_id, announce_hour_utc, announce_minute_utc, announce_message_template FROM server_settings')
        settings = cursor.fetchall()
        if not settings:
            logger.debug("誕生日通知タスク: 通知設定されているサーバーがありません。")
            return

        for setting in settings:
            guild_id = setting['guild_id']
            if guild_id in processed_guilds:
                continue
            announce_channel_id = setting['announce_channel_id']
            announce_hour_utc = setting['announce_hour_utc']
            announce_minute_utc = setting['announce_minute_utc']
            message_template = setting['announce_message_template']

            target_hour_utc = announce_hour_utc if announce_hour_utc is not None else DEFAULT_ANNOUNCE_HOUR_UTC
            target_minute_utc = announce_minute_utc if announce_minute_utc is not None else DEFAULT_ANNOUNCE_MINUTE_UTC
            time_source = "設定" if announce_hour_utc is not None else "デフォルト"

            if current_hour_utc == target_hour_utc and target_minute_utc <= current_minute_utc < target_minute_utc + loop_interval_minutes:
                logger.info(f"サーバー {guild_id} の通知時刻 ({target_hour_utc:02}:{target_minute_utc:02} UTC, {time_source}) の範囲内。誕生日チェック実行。")
                cursor.execute( 'SELECT display_name, mention_user_id FROM birthdays WHERE birthday = ? AND guild_id = ?', (today_jst_str, guild_id) )
                birthdays_today = cursor.fetchall()
                if birthdays_today:
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        logger.warning(f"...サーバー (ID: {guild_id}) が見つかりません。")
                        continue
                    if not announce_channel_id:
                        logger.warning(f"...サーバー {guild.name} (ID: {guild_id}) の通知チャンネルIDが無効です。")
                        continue
                    channel = guild.get_channel(announce_channel_id)
                    if not channel:
                        logger.warning(f"...サーバー {guild.name} の通知チャンネル (ID: {announce_channel_id}) が見つかりません。")
                        continue

                    mentions = []
                    names_only = []
                    for bday in birthdays_today:
                        name = bday['display_name']
                        mention_user_id = bday['mention_user_id']
                        names_only.append(name)
                        if mention_user_id:
                            member = guild.get_member(mention_user_id)
                            if member:
                                mentions.append(member.mention)
                            else:
                                logger.warning(f"...ユーザー (ID: {mention_user_id}, 名前: {name}) が見つかりません。")

                    celebrants_names = ', '.join(f"**{n}**" for n in names_only)
                    mention_str = ' '.join(mentions) + (' ' if mentions else '')

                    current_template = message_template if message_template else DEFAULT_ANNOUNCE_MESSAGE

                    try:
                        message = current_template.replace("<name>", celebrants_names)
                        # デフォルトテンプレート用のプレースホルダーも置換
                        message = message.format(
                            names=celebrants_names,
                            mentions=mention_str,
                            today_date=today_jst_str
                        )
                    except KeyError as e:
                        logger.error(f"サーバー {guild_id} のメッセージテンプレートフォーマットエラー: 不明なプレースホルダー {e}")
                        message = DEFAULT_ANNOUNCE_MESSAGE.format(
                            names=celebrants_names,
                            mentions=mention_str,
                            today_date=today_jst_str
                        )

                    try:
                        await channel.send(message)
                        logger.info(f"...サーバー {guild.name} のチャンネル {channel.name} に誕生日通知を送信しました。")
                        processed_guilds.add(guild_id)
                    except discord.Forbidden:
                        logger.error(f"...チャンネル {channel.name} への送信権限がありません。")
                    except discord.HTTPException as e:
                        logger.error(f"...通知送信中にHTTPエラー: {e}")
                    except Exception as e:
                        logger.error(f"...通知送信中に予期せぬエラー: {e}")
                else:
                    logger.info(f"...サーバー {guild_id} では今日 ({today_jst_str}) 誕生日の人はいません。")
                    processed_guilds.add(guild_id)
    except sqlite3.Error as e:
        logger.error(f"誕生日通知タスク中にデータベースエラーが発生しました: {e}")
    finally:
        if conn:
            conn.close()
        logger.debug("誕生日通知タスクチェック完了。")

@birthday_announce.before_loop
async def before_birthday_announce():
    await bot.wait_until_ready()
    logger.info("誕生日通知タスクの準備完了。ループを開始します。")

# --- Bot実行 ---
if __name__ == '__main__':
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("Botトークンが無効です。 .env ファイルを確認してください。")
    except Exception as e:
        logger.critical(f"Bot実行中に致命的なエラーが発生しました: {e}")
