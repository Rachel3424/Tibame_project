import requests
import json
from linebot import LineBotApi
from linebot.models import *
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import openai
from openai import OpenAI
import configparser
import pinecone

# Setup
config = configparser.ConfigParser()
config.read('config.ini')

channel_access_token = config.get('line-bot','channel_access_token')
secret = config.get('line-bot','channel_secret')

# rich_menu_image_path = "drive/MyDrive/richmenu.jpg"

# rich_menu_object = {
#     "size": {"width": 2500,"height": 1686},
#     "selected": True,
#     "name": "功能選單",
#     "chatBarText": "功能選單",
#     "areas":[
#       {
#         "bounds": {"x": 0, "y": 0, "width": 1250, "height": 843},
#         "action": {"type": "uri","label": "關於我們","uri": "https://liff.line.me/2002407298-NKqDGjqJ"}
#       },
#       {
#         "bounds": {"x": 1250, "y": 0, "width": 1250, "height": 843},
#         "action": {"type": "message", "text": "請用繁體中文簡要敘述您要詢問事件經過"}
#       },
#       {
#         "bounds": {"x": 0, "y": 843, "width": 1250, "height": 843},
#         "action": {"type": "uri","label": "網頁版","uri": "https://liff.line.me/2002407298-NKqDGjqJ"}
#       },
#       {
#         "bounds": {"x": 1250, "y": 843, "width": 1250, "height": 843},
#         "action": {"type": "message", "text": "加入法律智能小幫手連結: https://lin.ee/vNsToGI"}
#       }
#   ]
# }

# # Create a rich menu
# create_rich_menu_url = "https://api.line.me/v2/bot/richmenu"
# create_rich_menu_headers = {
#     "Authorization": "Bearer " + channel_access_token,
#     "Content-Type": "application/json"
# }
# create_rich_menu_response = requests.post(create_rich_menu_url, headers=create_rich_menu_headers, json=rich_menu_object)
# create_rich_menu_response.raise_for_status()

# # Get the rich menu ID
# rich_menu_id = create_rich_menu_response.json()["richMenuId"]

# # Upload the rich menu image
# upload_rich_menu_image_url = "https://api-data.line.me/v2/bot/richmenu/" + rich_menu_id + "/content"
# upload_rich_menu_image_headers = {
#     "Authorization": "Bearer " + channel_access_token,
#     "Content-Type": "image/jpeg"
# }
# upload_rich_menu_image_data = open(rich_menu_image_path, "rb").read()
# upload_rich_menu_image_response = requests.post(upload_rich_menu_image_url, headers=upload_rich_menu_image_headers, data=upload_rich_menu_image_data)
# upload_rich_menu_image_response.raise_for_status()

# # Set the default rich menu
# set_default_rich_menu_url = "https://api.line.me/v2/bot/user/all/richmenu/" + rich_menu_id
# set_default_rich_menu_headers = {
#     "Authorization": "Bearer " + channel_access_token
# }
# set_default_rich_menu_response = requests.post(set_default_rich_menu_url, headers=set_default_rich_menu_headers)
# set_default_rich_menu_response.raise_for_status()

# # Print the result
# print("Rich menu created and uploaded successfully!")



# Flask
app = Flask(__name__)

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(secret)


@app.route("/", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

# user問題查詢pinecone
def init_pinecone(index_name):
    pinecone.init(
        api_key = config.get("pinecone", "api_key"),
        environment='gcp-starter'
    )
    index = pinecone.Index(index_name)
    return index

def get_embedding(question):
    openai.api_key = config.get("OpenAI", "api_key")
    response = openai.Embedding.create(
    model="text-embedding-ada-002",
    input = question
    )
    # 提取生成文本中的嵌入向量
    embedding = response['data'][0]['embedding']
    
    return embedding

def search_from_pinecone(index, query_embedding, k=1):
    results = index.query(vector=query_embedding,
                          top_k=k, include_metadata=True, namespace='first_try')
    return results

def fetch_db_or_ai(question: str):
    index = init_pinecone("test01")
    query_embedding = get_embedding(question)
    qa_results = search_from_pinecone(index, query_embedding, k=10)
    
    similarity_matches = []
    
    for every_info in qa_results['matches']:
        # If score >= 0.8
        if every_info['score'] >= 0.8:
            temp={}
            temp['question']=every_info['metadata']['question']
            temp['answer']=every_info['metadata']['answer']
            temp['score']=every_info['score']

            similarity_matches.append(temp)

    if similarity_matches==[]:
        return 'ai'
    else:
        return similarity_matches

# OpenAI model
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_input = event.message.text
    result = fetch_db_or_ai(user_input)

    if result == 'ai':
        client = OpenAI(organization=config.get('OpenAI','organization'),
                            api_key=config.get('OpenAI','api_key'))
        response = client.chat.completions.create(
            model=config.get('OpenAI','model'),
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_input}
            ]
        )

        generated_text = response.choices[0].message.content.strip()


        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=generated_text)
        )
    else:
        return 'similarity_matches'
        # # 如果 fetch_db_or_gpt 回傳其他結果，例如相似問題的匹配，可以進行相應的處理
        # # 例如，將匹配的問題和回答回覆給使用者
        # for match in result:
        #     line_bot_api.reply_message(
        #         event.reply_token,
        #         TextSendMessage(text=f"Question: {match['question']}\nAnswer: {match['answer']}\nScore: {match['score']}")
        #     )


if __name__ == "__main__":
  app.run()