import io
import re
import os
import sys
import time
import glob
import json
import httplib2
from googleapiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from fuzzywuzzy import fuzz
from tqdm import tqdm
import logging


class TranslationModule():
    def __init__(self, path, result_path):
        self.module_path = os.path.dirname(os.path.realpath(sys.argv[0]))
        # 取得API登入驗證檔路徑(模組路徑/auth)
        self.auth = os.path.join(self.module_path, 'auth')
        # Google API URL
        self.SCOPES = 'https://www.googleapis.com/auth/drive'
        # 驗證檔 client_id.json
        self.CLIENT_SECRET_FILE = os.path.join(self.auth, 'client_id.json')
        # Google 帳號專案名稱
        self.APPLICATION_NAME = 'Python OCR'
        # 欲OCR的json path(含檔名)
        self.path = path
        # 產出result的路徑(含檔名)
        self.result_path = result_path
        self.do_translation()

    # 登入Google API method
    def get_credentials(self):
        credential_path = os.path.join(self.auth, 'google-ocr-credential.json')
        store = Storage(credential_path)
        credentials = store.get()
        if not credentials or credentials.invalid:
            flow = client.flow_from_clientsecrets(self.CLIENT_SECRET_FILE, self.SCOPES)
            flow.user_agent = self.APPLICATION_NAME
            credentials = tools.run_flow(flow, store)
        return credentials

    def do_translation(self):
        # exception 重試次數
        retries = 5
        test_date = str(time.strftime("%Y%m%d%H%M%S", time.localtime()))
        # 模組執行時的log, 等級為debug
        log_file = 'translation_{}.log'.format(test_date)
        file_handler = logging.FileHandler(filename=os.path.join(self.module_path, log_file))
        stdout_handler = logging.StreamHandler(sys.stdout)
        handlers = [file_handler, stdout_handler]
        logging.basicConfig(
            level=logging.DEBUG,
            format='[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s',
            handlers=handlers
        )
        logger = logging.getLogger('translation')
        text_file = open(self.result_path, "w", encoding="utf-8")

        # 登入Google API
        credentials = self.get_credentials()
        logger.info("Got Translation credentials.")
        http = credentials.authorize(httplib2.Http())
        logger.info("Pass Authentication.")
        service = discovery.build('drive', 'v3', http=http)

        # 讀取OCR json
        with open(self.path, encoding="utf-8") as reader:
            jf = json.loads(reader.read())

        # result的json dictionary
        json_result = dict()
        for index in tqdm(jf):
            for retry in range(retries):
                try:
                    ocr_dict = dict()
                    ocr_result = "fail"
                    ocr_course = 'file not found'
                    ocr_answer = ''
                    answer = jf[index]['answer']
                    pic_path = jf[index]['pic']
                    ocr_mode = jf[index]['mode']
                    if pic_path != '':
                        img_temp = glob.glob(pic_path)
                        if len(img_temp) > 0:
                            # 上傳圖片至Google Drive
                            imgfile = img_temp[0]
                            logger.info("imgfile : {}".format(imgfile))
                            txtfile = os.path.join(self.module_path, 'translation.tmp')
                            mime = 'application/vnd.google-apps.document'
                            res = service.files().create(
                                body={
                                    'name': imgfile,
                                    'mimeType': mime
                                },
                                media_body=MediaFileUpload(imgfile, mimetype=mime, resumable=True)
                            ).execute()

                            # 將檔片以文字檔格式下載 , 則完成OCR
                            downloader = MediaIoBaseDownload(
                                io.FileIO(txtfile, 'wb'),
                                service.files().export_media(fileId=res['id'],
                                                             mimeType="text/plain")
                            )
                            done = False
                            while done is False:
                                status, done = downloader.next_chunk()
                                service.files().delete(fileId=res['id']).execute()

                            # 讀取並解析下載的文字檔
                            temp_data = open(os.path.join(self.module_path, 'translation.tmp'), 'r',
                                             encoding='utf8').read()
                            if answer == '':
                                ocr_answer = temp_data
                                ocr_result = ''
                                ocr_course = ''
                            else:
                                if ocr_mode.lower() == 'abs':
                                    temp_data = ' ' + temp_data + ' '
                                    find_match = re.findall('[\s]' + answer + '[\s]', temp_data)
                                    find_match_case = re.findall('[\s]' + answer.lower() + '[\s]',
                                                                 temp_data.lower())
                                else:
                                    find_match = re.findall(answer, temp_data)
                                    find_match_case = re.findall(answer.lower(), temp_data)
                                str_match = len(find_match)
                                str_match_case = len(find_match_case)
                                if str_match > 1:
                                    ocr_course = 'duplicate {} times'.format(str_match)
                                    ocr_answer = answer
                                elif str_match == 1:
                                        ocr_result = 'pass'
                                        ocr_answer = answer
                                        ocr_course = ""
                                elif str_match_case > 0:
                                    ocr_course = 'case not match'
                                    ans_index = temp_data.lower().index(answer.lower())
                                    ocr_answer = temp_data[ans_index:ans_index + len(answer)]
                                else:
                                    # 先比對移除空白跟.之後的結果
                                    """temp_data_replace = temp_data.replace(" ", "").replace(".", "")
                                    temp_answer = answer.replace(" ", "").replace(".", "")"""
                                    temp_data_replace = re.sub('\s', '', temp_data)
                                    temp_answer = re.sub('\s', '', answer)
                                    temp_data_symbol = re.sub('\W', '', temp_data)
                                    temp_answer_symbol = re.sub('\W', '', answer)
                                    if ocr_mode.lower() == 'abs':
                                        temp_data_replace = ' ' + temp_data_replace + ' '
                                        find_match_replace = re.findall('[\s]' + temp_answer +'[\s]', temp_data_replace)
                                        temp_data_symbol = ' ' + temp_data_symbol + ' '
                                        find_match_symbol = re.findall('[\s]' + temp_answer_symbol + '[\s]',
                                                                        temp_data_symbol)
                                    else:
                                        find_match_replace = re.findall(temp_answer, temp_data_replace)
                                        find_match_symbol = re.findall(temp_answer_symbol, temp_data_symbol)
                                    str_match_replace = len(find_match_replace)
                                    str_match_symbol = len(find_match_symbol)
                                    if str_match_replace == 1:
                                        ocr_result = 'pass'
                                        """ocr_course = 'skip blanks and .'"""
                                        ocr_course = 'Skip whitespace and line breaks'
                                        ans_index_replace = temp_data_replace.lower().index(temp_answer.lower())
                                        ocr_answer = temp_data_replace[
                                                     ans_index_replace:ans_index_replace + len(temp_answer)]
                                    elif str_match_symbol == 1:
                                        ocr_result = 'pass'
                                        ocr_course = 'Skip whitespace and line breaks and punctuation'
                                        ans_index_replace = temp_data_symbol.lower().index(temp_answer_symbol.lower())
                                        ocr_answer = temp_data_symbol[
                                                     ans_index_replace:ans_index_replace + len(temp_answer_symbol)]
                                    else:
                                        # 比對Answer結果, 以Levenshtein Distance演算法計算符合程度
                                        """str_answer_array = re.split('\s', answer)
                                        str_answer_len = len(str_answer_array)
                                        if str_answer_len == 1:
                                            temp_data_list = re.split('[\s]', temp_data)
                                        else:
                                            temp_data_list = temp_data.split('\n')
                                        result_value_list = []
                                        for ocr_str in temp_data_list:
                                            result_value_list.append(fuzz.ratio(answer, ocr_str))
                                        match_value = max(result_value_list)
                                        match_index = result_value_list.index(match_value)"""
                                        ocr_course = 'Can not find the string'
                                        ocr_answer = temp_data

                    logger.info(
                        " --- Translation result --- answer : {} , pic : {} , result : {} , course : {} , ocr : {}".format(
                            answer.encode("utf8").decode("cp950", "ignore"),
                            pic_path.encode("utf8").decode("cp950", "ignore"),
                            ocr_result.encode("utf8").decode("cp950", "ignore"),
                            ocr_course.encode("utf8").decode("cp950", "ignore"),
                            ocr_answer.encode("utf8").decode("cp950", "ignore")))
                    ocr_dict['answer'] = answer
                    ocr_dict['pic'] = pic_path
                    ocr_dict['result'] = ocr_result
                    ocr_dict['course'] = ocr_course
                    ocr_dict['ocr'] = ocr_answer
                    json_result[index] = ocr_dict
                    # json.dump(json_result, text_file, indent=4, ensure_ascii=False)
                except Exception as e:
                    logger.exception("Exception occurred", exc_info=True)
                    if retry < retries - 1:
                        continue
                    else:
                        break
                break
        json.dump(json_result, text_file, indent=4, ensure_ascii=False)
        print("Result file : " + text_file.name)
        text_file.close()


if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("-p", required=True,
                    help="json file path of translation list")
    ap.add_argument("-r", required=True,
                    help="full file path of result json")
    args = vars(ap.parse_args())
    TranslationModule(path=args['p'], result_path=args['r'])
    # TranslationModule("E:/TV/numbers/1/amount_17.json", "d:/kkkk.json", "")
