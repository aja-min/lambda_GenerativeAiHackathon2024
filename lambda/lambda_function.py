import os
import sys
import logging
import requests
import json
from io import BytesIO
from PIL import Image

from linebot import (LineBotApi, WebhookHandler)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, ImageSendMessage)
from linebot.exceptions import (LineBotApiError, InvalidSignatureError)

logger = logging.getLogger()
logger.setLevel(logging.ERROR)

# LINEBOTと接続するための記述
# 環境変数からLINEBotのチャンネルアクセストークンとシークレットを読み込む
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)

# 無いならエラー
if channel_secret is None:
    logger.error('Specify LINE_CHANNEL_SECRET as environment variable.')
    # sys.exit(1)
if channel_access_token is None:
    logger.error('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    # sys.exit(1)

# apiとhandlerの生成（チャンネルアクセストークンとシークレットを渡す）
line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# chatgptとの接続準備
chatgpt_url = "https://api.openai.com/v1/chat/completions"
request_headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}"
}

# 画像生成メソッド
def generate_image(prompt):
    openai_image_url = "https://api.openai.com/v1/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}"
    }
    data = {
        "model": "image-alpha-001",
        "prompt": prompt,
        "num_images": 1,
        "size": "1024x1024"
    }
    response = requests.post(openai_image_url, headers=headers, json=data)
    if response.status_code == 200:
        result = response.json()
        image_url = result['data'][0]['url']
        return image_url
    else:
        logger.error(f"画像生成に失敗しました。ステータスコード: {response.status_code}, レスポンス: {response.text}")
        return None

# 画像をダウンロードするメソッド
def download_image(image_url):
    response = requests.get(image_url)
    if response.status_code == 200:
        image = Image.open(BytesIO(response.content))
        return image
    else:
        logger.error(f"画像のダウンロードに失敗しました。ステータスコード: {response.status_code}, レスポンス: {response.text}")
        return None

# Lambdaのメインの動作
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

    # メッセージを受け取る・受け取ったら受け取ったテキストを返信する
    @handler.add(MessageEvent, message=TextMessage)
    def message(line_event):
        # 受け取ったテキスト
        text = line_event.message.text

        # メッセージに入ってて欲しい単語
        validate_words = ["名前", "趣味", "一言", "テイスト"]
        if not all(word in text for word in validate_words):
            line_bot_api.reply_message(line_event.reply_token, TextSendMessage(text="フォーマットにしたがって入力してみてね！"))

        # chatgptにリクエストする
        request_data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "あなたは親切で丁寧な自己紹介生成マシンです。ユーザーから「名前」、「趣味」、「一言」と、自己紹介の希望テイストが送られて来るので、なるべく自然な言葉で100文字程度で自己紹介文を生成してください。"},
                {"role": "user", "content": text }
            ]
        }

        response = requests.post(chatgpt_url, headers=request_headers, data=json.dumps(request_data))

        if response.status_code == 200:
            result = response.json()
            answer = result["choices"][0]["message"]["content"]

            # OpenAIで画像生成
            image_prompt = (
                "Create an image based on the following instructions: "
                "1. The background should be plain white. "
                "2. There should be only one character. "
                "3. The character should be standing upright in the center of the image. "
                "4. The character should be looking directly at the camera. "
                "5. The character should not be holding anything in their hands. "
                "6. The character should have their mouth closed. "
                "7. The character's mouth should not be covered. "
                "8. The image should be square in shape. "
                "Character details: "
                "1. The character should be a female student attending a Japanese school. "
                "2. The character should have a keen interest in technology. "
                "3. The character should have a bright expression with a smile. "
                "4. The character should have sparkling eyes. "
                "5. The character should exude positive energy. "
                "Please ensure that the image is recognizable as a human face."
            )

            image_url = generate_image(image_prompt)

            if image_url:
                # 画像生成に成功した場合
                line_bot_api.reply_message(line_event.reply_token, TextSendMessage(text=f"画像生成に成功しました: {image_url}"))
            else:
                # 画像生成に失敗した場合
                line_bot_api.reply_message(line_event.reply_token, TextSendMessage(text="画像生成に失敗しました。"))

        else:
            line_bot_api.reply_message(line_event.reply_token, TextSendMessage(text=f"Error: {response.status_code}, {response.text}"))

    # 例外処理としての動作
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
