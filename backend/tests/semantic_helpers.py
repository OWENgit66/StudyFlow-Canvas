"""Offline reviewer fixtures: no real provider or network access."""
import json


def semantic_response(user, judge=None):
    decisions = []
    for group in json.loads(user)['groups']:
        for claim in group['claims']:
            supported = True if judge is None else judge(claim, group['sources'])
            decisions.append({'claim_id': claim['claim_id'], 'supported': supported,
                              'reason': 'Supported by supplied source.' if supported else 'Not supported by cited source.',
                              'unsupported_parts': [] if supported else [claim['text']]})
    return json.dumps({'decisions': decisions})


def semantic_http_response(request):
    import httpx2 as httpx
    body = json.loads(request.content)
    openai = 'input' in body
    schema = body['text']['format']['schema'] if openai else None
    if openai:
        is_semantic = schema.get('title') == 'SemanticReview'
        user = body['input']
    else:
        is_semantic = 'Assess semantic support using ONLY' in body['messages'][0]['content']
        user = body['messages'][1]['content']
    if not is_semantic:
        return None
    content = semantic_response(user)
    if openai:
        return httpx.Response(200, json={'status':'completed','output':[
            {'type':'message','content':[{'type':'output_text','text':content}]}]})
    return httpx.Response(200, json={'choices':[{'finish_reason':'stop','message':{'content':content}}]})
