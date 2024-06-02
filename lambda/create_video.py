import os
import boto3
import requests
import time
import logging
from dataclasses import dataclass

logger = logging.getLogger()
logger.setLevel(logging.ERROR)

BUCKET_NAME = "selfintro-bot-bucket"
D_ID_API_URL = "https://api.d-id.com/talks"
OUTPUT_DIR = "/tmp"
DID_API_KEY = os.getenv('DID_API_KEY', None)
AUTHORIZATION_HEADER = f"Basic {DID_API_KEY}"

@dataclass
class Payload:
    # スクリプトのタイプ
    type: str = "text"
    # 字幕
    subtitles: bool = False
    # 音声合成プロバイダー
    provider_type: str = "microsoft"
    # 音声ID
    voice_id: str = ""
    # SSML（音声合成マークアップ）
    ssml: bool = True
    # 読み上げるテキスト
    input_text: str = ""
    # 出力フォーマット
    result_format: str = "mp4"
    # 全身が表示されるかどうか
    stitch: bool = True
    # 顔検出の有無を設定
    detect_faces: bool = True
    # 画像補正の有無を設定
    correct: bool = True
    # アニメーションする画像のURL
    source_url: str = ""
    # 動画のタイトル
    name: str = ""
    # 動画を永続的に保存するかどうかを設定（ダウンロードさせるのでFalse）
    persist: bool = False
    # 顔検出信頼度
    detect_confidence: float = 0.5
    # 顔遮蔽の信頼度
    face_occluded_confidence: float = 0.5

    def to_dict(self):
        return {
            "script": {
                "type": self.type,
                "subtitles": self.subtitles,
                "provider": {
                    "type": self.provider_type,
                    "voice_id": self.voice_id
                },
                "ssml": self.ssml,
                "input": self.input_text
            },
            "config": {
                "result_format": self.result_format,
                "stitch": self.stitch,
                "detect_faces": self.detect_faces,
                "correct": self.correct,
                "detect_confidence": self.detect_confidence,
                "face_occluded_confidence": self.face_occluded_confidence
            },
            "source_url": self.source_url,
            "name": self.name,
            "persist": self.persist
        }

    def set_values(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

def create(text, avatar_type):
    print("create method start")
    try:
        # パラメータの設定
        input_text = text
        # avatar_typeによって画像と音声を選択
        if avatar_type == "男":
            object_name = "images/generated_image_anime_man.png"
            voice_id = "ja-JP-KeitaNeural"
        elif avatar_type == "女":
            object_name = "images/generated_image_anime_woman.png"
            voice_id = "ja-JP-NanamiNeural"
        elif avatar_type == "動物":
            object_name = "images/generated_image_neko.png"
            voice_id = "ja-JP-AoiNeural"
        else:
            print("Unknown avatar type")
            raise ValueError("Unknown avatar type: " + avatar_type)

        # プリサインドURLを生成
        source_url = create_presigned_url(BUCKET_NAME, object_name)
        if not source_url:
            return None

        payload = Payload()
        payload.set_values(
            source_url=source_url,
            input_text=input_text,
            voice_id=voice_id
        )

        talk_id = create_video_request(payload)
        if not talk_id:
            return None

        # 動画のダウンロードURLを取得
        result_url = get_video_url(talk_id)
        if not result_url:
            return None

        # # 動画をダウンロード
        # file_name = f"{talk_id}.mp4"
        # output_path = os.path.join(OUTPUT_DIR, file_name)
        # if not download_video_from_url(result_url, output_path):
        #     return None

        # # ダウンロードした動画をS3にアップロード
        # s3_upload_object_name = f"movies/{file_name}"
        # if not upload_to_s3(output_path, BUCKET_NAME, s3_upload_object_name):
        #     return None

        return result_url

    except Exception as e:
        logger.error(f"An error occurred: {e}")
    return None

def create_presigned_url(bucket_name, object_name, expiration=3600):
    print("create_presigned_url start")
    """Generate a presigned URL to share an S3 object"""
    s3_client = boto3.client('s3')
    try:
        print("try s3_client.generate_presigned_url")
        response = s3_client.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': object_name},
                                                    ExpiresIn=expiration)
        print("create_presigned_url response get")
    except Exception as e:
        print(f"プリサインドURLの生成に失敗しました: {e}")
        return None

    return response

def create_video_request(payload):
    print("create_video_request start")
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": AUTHORIZATION_HEADER
    }

    # POSTリクエストを送信してレスポンスを受け取る
    post_response = requests.post(D_ID_API_URL, json=payload.to_dict(), headers=headers)
    print("post_response get")
    print(f"post_response: {post_response}")
    if post_response.status_code != 201:
        print(f"POSTリクエストが失敗しました。ステータスコード: {post_response.status_code}, レスポンス: {post_response.text}")
        return None

    post_response_data = post_response.json()

    # JSONデータから作成された動画のIDを取得
    talk_id = post_response_data.get('id', '')
    print(f"Created Talk ID: {talk_id}")

    return talk_id

def get_video_url(talk_id):
    print("get_video_url start")
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": AUTHORIZATION_HEADER
    }

    if talk_id:
        url = f"{D_ID_API_URL}/{talk_id}"
        while True:
            get_response = requests.get(url, headers=headers)
            if get_response.status_code != 200:
                print(f"GETリクエストが失敗しました。ステータスコード: {get_response.status_code}, レスポンス: {get_response.text}")
                return None

            get_response_data = get_response.json()
            status = get_response_data.get('status', '')
            if status == 'done':
                result_url = get_response_data.get('result_url', '')
                print(f"Result URL: {result_url}")

                if result_url:
                    return result_url
                else:
                    print(f"result_urlが見つかりません。 {get_response_data}")
                    return None
            elif status == 'error':
                print(f"動画の作成中にエラーが発生しました。 {get_response_data}")
                return None
            else:
                print(f"動画のステータス: {status}。しばらく待機します...")
                time.sleep(5)  # 5秒待機してから再度ステータスを確認
    else:
        print("動画IDの取得に失敗しました。")
        return None

def upload_to_s3(file_path, bucket_name, object_name):
    """Upload a file to an S3 bucket"""
    s3_client = boto3.client('s3')
    try:
        s3_client.upload_file(file_path, bucket_name, object_name)
        print(f"ファイルが {bucket_name}/{object_name} にアップロードされました。")
    except Exception as e:
        print(f"S3へのファイルアップロードに失敗しました: {e}")
        return False
    return True

def download_video_from_url(video_url, output_path):
    response = requests.get(video_url, stream=True)
    if response.status_code == 200:
        with open(output_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        print(f"動画が {output_path} にダウンロードされました。")
    else:
        print(f"動画のダウンロードに失敗しました。ステータスコード: {response.status_code}, レスポンス: {response.text}")
        return False
    return True
