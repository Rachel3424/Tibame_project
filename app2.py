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
        for match in result:
            line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"Question: {match['question']}\nAnswer: {match['answer']}\nScore: {match['score']}")
        )


if __name__ == "__main__":
  app.run()