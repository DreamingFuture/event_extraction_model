# Copyright (c) 2021 Baidu.com, Inc. All Rights Reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""duee 1.0 data predict post-process"""

import argparse
import json
from LAC import LAC
from utils.utils import read_by_lines, write_by_lines, extract_result, cnt_time
import Levenshtein

need_event_type = ['产品抽查', "产品行为-召回", '司法行为-罚款', '组织关系-裁员', '司法行为-举报', "项目投资"] # '司法行为-举报',  '财经/交易-出售/收购', '服务供货'

def fenci_youhua(news):
        # 装载LAC模型
        lac = LAC(mode='lac')
        for new in news: # 针对每一个json
            if len(new['event_list']): # 含有事件
                text = lac.run(new['text']) 
                
                for event in new['event_list']: # 针对每一个事件
                    arguments = []
                    for role in event['arguments']: # 针对每一个事件的arguments
                        arguments.append(role['argument'])
                    arguments_fenci = lac.run(arguments)
                    for index_argument in range(len(arguments_fenci)): # 针对每一个argument
                        for index_fenci in range(len(arguments_fenci[index_argument][0])): # 针对每一个argument的每一个分词结果
                            res = arguments_fenci[index_argument][0][index_fenci] # 每一个分词结果
                            res_argument = []
                            for index_text_fenci in range(len(text[0])):
                                if res in text[0][index_text_fenci]: 
                                    res_argument.append(text[0][index_text_fenci])
                                    # arguments_fenci[index_argument][0][index_fenci] = text[0][index_text_fenci]
                                    
                            # 对原来的进行替换
                            if len(res_argument) == 1:
                                arguments_fenci[index_argument][0][index_fenci] = res_argument[0]
                            else:
                                min_distance = 100
                                min_distance_item = arguments_fenci[index_argument][0][index_fenci]
                                for item in res_argument:
                                    distance = Levenshtein.distance(arguments_fenci[index_argument][0][index_fenci], item)
                                    if distance < min_distance:
                                        min_distance = distance
                                        min_distance_item = item
                                arguments_fenci[index_argument][0][index_fenci] = min_distance_item

                    for index_argument in range(len(arguments_fenci)): # 针对每一个argument
                        # argument = ''.join(arguments_fenci[index_argument][0])
                        argument = ''.join(sorted(set(arguments_fenci[index_argument][0]), key=arguments_fenci[index_argument][0].index)) # 去重
                        event['arguments'][index_argument]['argument'] = argument 
        return news

def merge_news(res:list) -> list:
    titles = dict()
    for record in res:
        text_id = record['id']
        # 存title
        if text_id[-1] == '0':
            titles[text_id] = record['text']
    
    content_list = []
    id1 = ''
    for item in res:
        if id1 == item['id'].split('-')[1]:
            texts += item['text'] # 拼接摘要
            event_list += item['event_list'] # 拼接抽取结果
            # print(item["id"])
        else:
            # 先存上一个新闻，id1不为0
            if id1:
                content_list.append({"id":f'id-{id1}', "title": titles[f'id-{id1}-0'] ,"text": texts, "event_list": event_list})
            # 继续下一个新闻
            id1 = item['id'].split('-')[1]
            texts = item['text']
            event_list = item['event_list']
    return content_list

def get_type(pred_event_trigger):
    trigger_type = []
    role_type = []
    for item in pred_event_trigger:
        item = json.loads(item)
        trigger_type.append(item['event_type'])
        role_type += [ role['role'] for role in item['role_list']]
    return trigger_type, role_type

def predict_data_process(trigger_file, role_file, schema_file, save_path):
    """predict_data_process"""
    pred_ret = []
    trigger_datas = read_by_lines(trigger_file)
    role_data = read_by_lines(role_file)
    schema_datas = read_by_lines(schema_file)
    trigger_types, role_types = get_type(schema_datas)
    print("trigger predict {} load from {}".format(len(trigger_datas), trigger_file))
    print("role predict {} load from {}".format(len(role_data), role_file))
    print("schema {} load from {}".format(len(schema_datas), schema_file))

    schema = {}
    for s in schema_datas:
        d_json = json.loads(s)
        schema[d_json["event_type"]] = [r["role"] for r in d_json["role_list"]]

    # process the role data
    sent_role_mapping = {}
    for d in role_data:
        d_json = json.loads(d)
        r_ret = extract_result(d_json["text"], d_json["pred"]["labels"])
        role_ret = {}
        for r in r_ret:
            role_type = r["type"]
            if role_type not in role_types:
                continue
            if role_type not in role_ret:
                role_ret[role_type] = []
            role_ret[role_type].append("".join(r["text"]))
        sent_role_mapping[d_json["id"]] = role_ret

    for d in trigger_datas:
        d_json = json.loads(d)
        t_ret = extract_result(d_json["text"], d_json["pred"]["labels"])
        
        # 保证pred_event_types里都是schema里面的事件类型，防止role进入
        pred_event_types = []
        temp = list(set([t["type"] for t in t_ret]))
        for item in temp:
            if item in trigger_types:
                pred_event_types.append(item)
        pred_event_trigger = dict()
        if "产品行为-召回" in pred_event_types:
            a = 1
        for t in t_ret:
            # if t["type"] not in trigger_types:
            #     continue
            if t["type"] in pred_event_trigger:
                pred_event_trigger[t["type"]] += '/'+''.join(t["text"])
            else:
                pred_event_trigger[t["type"]] = ''.join(t["text"])
        event_list = []
        for event_type in pred_event_types:  # 只有trigger触发了，对应的论元才会写到结果表中            
            # 不是需要的事件类型，continue
            if event_type not in need_event_type:
                continue
            # 后处理
            if event_type == "产品抽查":
                if '抽检' not in pred_event_trigger[event_type]:
                    continue
            elif event_type == "产品行为-召回":
                if '召回' not in pred_event_trigger[event_type]:
                    continue
            elif event_type == "司法行为-罚款":
                if '罚' not in pred_event_trigger[event_type]:
                    continue
            elif event_type == "司法行为-举报":
                if len(pred_event_trigger[event_type]) <= 1:
                    continue
            elif event_type == "组织关系-裁员":
                need_trigger = '裁员/削减/裁减/裁撤'.split('/')
                # trigger存在存1
                judge = [1 if item in pred_event_trigger[event_type] else 0 for item in need_trigger]
                # 任一need trigger存在，sum > 0
                judge = sum(judge)
                if not judge:
                    continue
            elif event_type == "财经/交易-出售/收购":
                pass
            elif event_type == "服务供货":
                need_trigger = '供应/供货/进口'.split('/')
                # trigger存在存1
                judge = [1 if item in pred_event_trigger[event_type] else 0 for item in need_trigger]
                # 任一need trigger存在，sum > 0
                judge = sum(judge)
                if not judge:
                    continue
            elif event_type == "项目投资":
                if '投资' not in pred_event_trigger[event_type]:
                    continue
                
            role_list = schema[event_type]
            arguments = []
            for role_type, ags in sent_role_mapping[d_json["id"]].items():
                if role_type not in role_list:
                    continue
                for arg in ags:
                    if len(arg) == 1:
                        continue
                    arguments.append({"role": role_type, "argument": arg})
            event = {"event_type": event_type,"trigger": pred_event_trigger[event_type], "arguments": arguments}
            event_list.append(event)
        if 'news_id' in d_json:
            pred_ret.append({
                "id": d_json["id"],
                "news_id":d_json["news_id"],
                "text": d_json["text"],
                "event_list": event_list
            })
        else:
            pred_ret.append({
                "id": d_json["id"],
                "text": d_json["text"],
                "event_list": event_list
            })
    
    # pred_ret = merge_news(pred_ret)
    # fenci_youhua(pred_ret)
    pred_ret = [json.dumps(r, ensure_ascii=False) for r in pred_ret]
    print("submit data {} save to {}".format(len(pred_ret), save_path))
    write_by_lines(save_path, pred_ret)

@cnt_time 
def postprocess_main(predict_save_path:str = None, output_path:str = None):
    
    if predict_save_path is None:
        raise TypeError("predict_save_path 不能为 None")

    if output_path is None:
        raise TypeError("output_path 不能为 None")


    parser = argparse.ArgumentParser(
        description="Official evaluation script for DuEE version 1.0")
    parser.add_argument(
        "--trigger_file", 
        default=predict_save_path,
        help="trigger model predict data path"
        )
    parser.add_argument(
        "--role_file", 
        default=predict_save_path,
        help="role model predict data path" 
        )
    parser.add_argument(
        "--schema_file", 
        default="./conf/DuEE1.0/event_schema.json",
        help="schema file path", 
        )
    parser.add_argument(
        "--save_path", 
        default=output_path,
        help="save file path", 
        )
    args = parser.parse_args()
    predict_data_process(args.trigger_file,
                         args.role_file,
                         args.schema_file,
                         args.save_path)    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Official evaluation script for DuEE version 1.0")
    parser.add_argument(
        "--trigger_file", help="trigger model predict data path", required=True)
    parser.add_argument(
        "--role_file", help="role model predict data path", required=True)
    parser.add_argument("--schema_file", help="schema file path", required=True)
    parser.add_argument("--save_path", help="save file path", required=True)
    args = parser.parse_args()
    predict_data_process(args.trigger_file,
                         args.role_file,
                         args.schema_file,
                         args.save_path)
