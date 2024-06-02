import os
import sys
import logging
import requests
import json
import re
import create_video

from linebot import (LineBotApi, WebhookHandler)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
from linebot.exceptions import (LineBotApiError, InvalidSignatureError)

logger = logging.getLogger()
logger.setLevel(logging.ERROR)

#LINEBOTと接続するための記述
#環境変数からLINEBotのチャンネルアクセストークンとシークレットを読み込む
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

#無いならエラー
if channel_secret is None:
    logger.error('Specify LINE_CHANNEL_SECRET as environment variable.')
    # sys.exit(1)
if channel_access_token is None:
    logger.error('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    # sys.exit(1)

#apiとhandlerの生成（チャンネルアクセストークンとシークレットを渡す）
line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# chatgptとの接続準備
chatgpt_url = "https://api.openai.com/v1/chat/completions"
request_headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}"
}

line_format = """フォーマットにしたがって入力してみてね！

名前:
趣味:
一言:
自己紹介のテイスト:
アバタータイプ:
"""

#Lambdaのメインの動作
def lambda_handler(event, context):
    print("Event:", event)
    # 認証用のx-line-signatureヘッダー
    if "headers" in event and "x-line-signature" in event["headers"]:
        signature = event["headers"]["x-line-signature"]
    else:
        # エラーレスポンスを返す
        return {
            "isBase64Encoded": False,
            "statusCode": 400,
            "headers": {},
            "body": "Missing x-line-signature header"
        }

    body = event["body"]
    # リターン値の設定
    ok_json = {
        "isBase64Encoded": False,
        "statusCode": 200,
        "headers": {},
        "body": ""
    }
    error_json = {
        "isBase64Encoded": False,
        "statusCode": 500,
        "headers": {},
        "body": "Error"
    }

    #メッセージを受け取る・受け取ったら受け取ったテキストを返信する
    @handler.add(MessageEvent, message=TextMessage)
    def message(line_event):
        # 受け取ったテキスト
        """
        フォーマットはこの通り
        ------------------------
        名前: hogehoge
        趣味: fugafuga
        一言: piyopiyo
        自己紹介のテイスト: hahahaha
        アバタータイプ: xxxx
        ------------------------
        """
        text = line_event.message.text
        parsed_message = parse_message(text)

        if not parsed_message:
            line_bot_api.reply_message(line_event.reply_token, TextSendMessage(text=line_format))


        # chatgptにリクエストする
        request_data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "あなたは親切で丁寧な自己紹介生成マシンです。ユーザーから「名前」、「趣味」、「一言」と、自己紹介の希望テイストが送られて来るので、なるべく自然な言葉で100文字程度で自己紹介文を生成してください。"},
                {"role": "user", "content": f"名前は{parsed_message.get("名前")}で、趣味は{parsed_message.get("趣味")}です。{parsed_message.get("一言")}。{parsed_message.get("自己紹介のテイスト")}な感じで自己紹介を作成してください。" }
            ]
        }

        response = requests.post(chatgpt_url, headers=request_headers, data=json.dumps(request_data))

        print(f"OpenAI response: {response.json}")
        if response.status_code == 200:
            print("response.status_code == 200")
            result = response.json()
            answer = result["choices"][0]["message"]["content"]

            try:
                print("create_video.create start")
                # 一旦コメントアウトしたよ！
                video = create_video.create(answer, parse_avatar(parsed_message.get("アバタータイプ")))
                # video = None
                print("create_video.create end video: ", video)
                if video:
                    line_bot_api.reply_message(line_event.reply_token, TextSendMessage(text=video))
                else:
                    line_bot_api.reply_message(line_event.reply_token, TextSendMessage(text=f"{parsed_message.get("名前")}、{parsed_message.get("趣味")}、{parsed_message.get("一言")}、{parsed_message.get("自己紹介のテイスト")}、{parsed_message.get("アバタータイプ")}"))
                    logger.error("Failed to create video.")
                    print("Failed to create video.")
            except Exception as e:
                logger.error(f"Error in create_video.create: {e}")
                print(f"Error in create_video.create: {e}")

            # いったんURLを返す
            line_bot_api.reply_message(line_event.reply_token, TextSendMessage(text=video))

        else:
            line_bot_api.reply_message(line_event.reply_token, TextSendMessage(f"Error: {response.status_code}, {response.text}"))

    #例外処理としての動作
    try:
        handler.handle(body, signature)
    except LineBotApiError as e:
        logger.error("Got exception from LINE Messaging API: %s\n" % e.message)
        for m in e.error.details:
            logger.error("  %s: %s" % (m.property, m.message))
        return error_json
    except InvalidSignatureError:
        return error_json

    return ok_json

def parse_message(message):
    # 正規表現パターン
    pattern = r"名前:(.*)趣味:(.*)一言:(.*)自己紹介のテイスト:(.*)アバタータイプ:(.*)"

    # 全角コロンを半角コロンに置換
    message = message.replace("：", ":")

    # 正規表現でメッセージを検索
    match = re.search(pattern, message, re.DOTALL)  # re.DOTALLは複数行にまたがる場合に必要

    if match:
        # 抽出した情報を辞書に格納
        data = {
            "名前": match.group(1).strip(),
            "趣味": match.group(2).strip(),
            "一言": match.group(3).strip(),
            "自己紹介のテイスト": match.group(4).strip(),
            "アバタータイプ": match.group(5).strip()
        }
        return data
    else:
        return None  # パース失敗

def parse_avatar(avatar_type):
    if "男" in avatar_type:
        return "男性"
    elif "女" in avatar_type:
        return "女性"
    else:
        return "動物"