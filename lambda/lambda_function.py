import os
import sys
import logging
import requests
import json
import re
import create_video

from linebot import (LineBotApi, WebhookHandler)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, ImageMessage, VideoSendMessage)
from linebot.exceptions import (LineBotApiError, InvalidSignatureError)

logger = logging.getLogger()
logger.setLevel(logging.ERROR)

#LINEBOTと接続するための記述
#環境変数からLINEBotのチャンネルアクセストークンとシークレットを読み込む
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

# ユーザーの状態を保持する辞書
user_state = {}

# 質問リスト
questions = [
    "名前は？",
    "趣味は？",
    "一言！",
    "自己紹介のテイストは？",
    "アバターを使いますか？（はい/いいえ）"
]

# chatgptとの接続準備
chatgpt_url = "https://api.openai.com/v1/chat/completions"
request_headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}"
}

def ask_next_question(user_id, reply_token):
    """
    ユーザーの状態に基づいて次の質問を送信する。
    すべての質問が終わった後はChatGPTを呼び出し、アバターの質問を行う。
    """
    state = user_state[user_id]
    
    # まだ通常の質問が残っている場合
    if state["step"] < len(questions):
        next_question = questions[state["step"]]
        line_bot_api.reply_message(reply_token, TextSendMessage(text=next_question))
        state["step"] += 1

    # アバターを使うかの質問に答えた後
    elif state["step"] == len(questions):
        state["data"]["アバターを使うか"] = state["last_message"]
        if state["last_message"] == "はい":
            line_bot_api.reply_message(reply_token, TextSendMessage(text="アバターの性別をどちらにするか教えてください (男性/女性)"))
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="プロフィール画像をアップロードしてください ※バストアップで人の顔とはっきりわかる画像をあげてください"))
        state["step"] += 1

    # アバターの性別を答えた後または画像アップロード後の処理
    elif state["step"] == len(questions) + 1:
        if state["data"]["アバターを使うか"] == "はい":
            state["data"]["性別"] = state["last_message"]
        else:
            state["data"]["プロフィール画像"] = "アップロード済み"

        # ChatGPTを呼び出す
        call_chatgpt(user_id, reply_token)
        reset_user_state(user_id)

def call_chatgpt(user_id, reply_token):
    """
    ChatGPTを呼び出してユーザーの自己紹介文を生成し、アバターの質問を行う。
    """
    user_data = user_state[user_id]["data"]
    # request_data = {
    #     "model": "gpt-3.5-turbo",
    #     "messages": [
    #         {"role": "system", "content": "あなたは親切で丁寧な自己紹介生成マシンです。ユーザーから「名前」、「趣味」、「一言」と、自己紹介の希望テイストが送られて来るので、なるべく自然な言葉で漢字を含む100文字程度で自己紹介文を生成してください。そしてそれを全部ひらがなに直してください。"},
    #         {"role": "user", "content": f"名前は{user_data.get("名前")}で、趣味は{user_data.get("趣味")}です。{user_data.get("一言")}.{user_data.get("自己紹介のテイスト")}な感じで自己紹介を作成してください。"}
    #     ]
    # }
    request_data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {
                "role": "system",
                "content": (
                    "あなたはクリエイティブで効果的な自己紹介プロフィールを構築するライティングスキルを持っています。"
                    "また、日本の漫画やエンターテインメント、ミームについても詳しいです。"
                    "ひらがなだけを使って自然な自己紹介文を生成してください。"
                )
            },
            {
                "role": "user",
                "content": (
                    "以下の条件を使って、面白くて個性的な自己紹介文を作ってください。"
                    "1. 読み手に明確で分かりやすい印象を与えるように、言葉選びに注意してください。\n"
                    "3. 漢字も含めて書くと100文字程度になるように作ってください。\n\n"
                    f"なまえ: {user_data.get('名前')}\n"
                    f"しゅみ: {user_data.get('趣味')}\n"
                    f"ひとこと: {user_data.get('一言')}\n"
                    f"ていすと: {user_data.get('自己紹介のテイスト')}\n\n"
                )
            }
        ]
    }

    response = requests.post(chatgpt_url, headers=request_headers, data=json.dumps(request_data))

    if response.status_code == 200:
        result = response.json()
        answer = result["choices"][0]["message"]["content"]
        # 動画生成
        video_message = create_video_message(answer, user_data.get("性別"), user_data.get("画像"))
        line_bot_api.reply_message(reply_token, video_message)
    else:
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"Error: {response.status_code}, {response.text}"))

def create_video_message(text, avatar_type, profile_picture):
    video_s3_url, thumbnail_s3_url = create_video.create(text, avatar_type, profile_picture)
    print("create_video.create end video: ", video_s3_url, thumbnail_s3_url)
    if video_s3_url:
        # LINEに動画を送信
        video_message = VideoSendMessage(
            original_content_url=video_s3_url,
            preview_image_url=thumbnail_s3_url
        )
    return video_message

def reset_user_state(user_id):
    """
    ユーザーの状態をリセットする。
    """
    user_state[user_id] = {"step": 0, "data": {}, "last_message": ""}

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
    def handle_text_message(line_event):
        user_id = line_event.source.user_id
        text = line_event.message.text

        # ユーザーの状態を取得または初期化
        if user_id not in user_state:
            reset_user_state(user_id)

        state = user_state[user_id]
        state["last_message"] = text

        # 現在の質問に対する回答を保存
        if state["step"] > 0 and state["step"] <= len(questions):
            question_key = ["名前", "趣味", "一言", "自己紹介のテイスト", "アバターを使うか"][state["step"] - 1]
            state["data"][question_key] = text

        ask_next_question(user_id, line_event.reply_token)

    @handler.add(MessageEvent, message=ImageMessage)
    def handle_image_message(line_event):
        user_id = line_event.source.user_id

        # ユーザーの状態を取得または初期化
        if user_id not in user_state:
            reset_user_state(user_id)

        state = user_state[user_id]

        if state["step"] == len(questions) + 1 and state["data"]["アバターを使うか"] == "いいえ":
            message_content = line_bot_api.get_message_content(line_event.message.id)
            with open(f"/tmp/{line_event.message.id}.jpg", "wb") as f:
                for chunk in message_content.iter_content():
                    f.write(chunk)
            state["data"]["画像"] = f"/tmp/{line_event.message.id}.jpg"
            ask_next_question(user_id, line_event.reply_token)

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
