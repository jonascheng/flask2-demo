from flask import Flask
from time import sleep
from aredis import StrictRedis
from threading import Lock
from threading import Thread
from queue import Queue
import aiohttp
import asyncio
import requests
import threading
import redis
import os

from flask_cors import CORS
from werkzeug.serving import WSGIRequestHandler

class ProcessSingleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        pid = os.getpid()
        cls._instances.setdefault(cls, {})
        if not pid in cls._instances[cls]:
            cls._instances[cls][pid] = super(ProcessSingleton, cls).__call__(*args, **kwargs)
            print(f'init process singleton for {cls}: {pid}')
        return cls._instances[cls][pid]

class ThreadSingleton(type):
    '''Keep the singleton for each thread

    Notice that the singleton for each will NOT release after use.
    '''
    _instances = {}
    def __call__(cls, *args, **kwargs):
        thread_id = threading.current_thread().ident
        pid = os.getpid()
        id_key = (thread_id, pid)
        cls._instances.setdefault(cls, {})
        if not id_key in cls._instances[cls]:
            cls._instances[cls][id_key] = super(ThreadSingleton, cls).__call__(*args, **kwargs)
            print(f'init thread singleton for {cls}: {id_key}')
        return cls._instances[cls][id_key]

class EventLoop(metaclass=ProcessSingleton):
    '''For run a event loop in each process
    '''
    START_SLEEP = 0.02
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.conn = aiohttp.TCPConnector(limit_per_host=10, force_close=False, loop=self.loop)
        self.consumer_thread = threading.Thread(target=self.start_consumer, daemon=True)
        self.consumer_thread.start()
        sleep(EventLoop.START_SLEEP) # wait till event loop is on

    def start_consumer(self):
        # Should inside a new thread
        self.loop.run_forever()

class AsyncRequest(metaclass=ThreadSingleton):
    '''Reuse event loop and aiohttp connection poll

    Notice that it will set_event_loop with a new event loop.
    '''
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.conn = aiohttp.TCPConnector(limit_per_host=10, force_close=False, loop=self.loop)

class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

class DrugSyncHelper(metaclass=Singleton):
    def __init__(self):
        self.lock = Lock()
        # self.redis_helper = StrictRedis(host="redis", db=0)
        self.redis_helper = redis.StrictRedis(host="redis", db=0)

        # commonly used
        self.db_raw_data = {}
        self.code2info = {}
        self.ver_no = {}
        self.drug_sets = {}

        """only 'drug_list' function will require this json for return so not storing dict"""
        self.drug_list_resp = {} # cache the resp string of the drug_list api

    # async def update_drug_list_from_redis(self):
    #     print(f'Update drug_list from redis')
    #     drug_resp = await self.redis_helper.get("test-key")
    #     self.set_drug_list_resp(drug_resp)

    # async def update_drug_set_from_redis(self):
    #     print(f'Update drug_set from redis')
    #     drug_set = await self.redis_helper.get("test-key")
    #     self.set_drug_set(drug_set)

    # async def update_code2info_from_redis(self):
    #     print(f'Update code2info from redis')
    #     code2info = await self.redis_helper.get("test-key")
    #     self.set_code2info(code2info)

    def update_drug_list_from_redis(self):
        print(f'Update drug_list from redis')
        drug_resp = self.redis_helper.get("test-key")
        self.set_drug_list_resp(drug_resp)

    def update_drug_set_from_redis(self):
        print(f'Update drug_set from redis')
        drug_set = self.redis_helper.get("test-key")
        self.set_drug_set(drug_set)

    def update_code2info_from_redis(self):
        print(f'Update code2info from redis')
        code2info = self.redis_helper.get("test-key")
        self.set_code2info(code2info)

    def set_drug_list_resp(self, drug_resp):
        print(f'set_drug_list_resp')
        with self.lock:
            self.drug_list_resp = drug_resp

    def set_drug_set(self, drug_set):
        print(f'set_drug_set')
        with self.lock:
            self.drug_sets = drug_set

    def set_code2info(self, code2info):
        print(f'set_code2info')
        with self.lock:
            self.code2info = code2info

class Subscriber(metaclass=Singleton):
    def __init__(self):
        # print(f"Created a thread for listening")
        self.local_cache = DrugSyncHelper()

        self.update_queue = Queue() # set up a queue to prevent repetitive calls
        self.queue_elements = set()

        self.t_listen_pub = threading.Thread(target = self.listen_pub)
        self.t_listen_pub.setDaemon(True)
        self.t_listen_pub.start()

        loop = AsyncRequest().loop
        self.t_syncdb_queue = threading.Thread(target = self.process_update_job, args=(loop,))
        self.t_syncdb_queue.setDaemon(True)
        self.t_syncdb_queue.start()

    # async def update_machine(self):
    #     try:
    #         print("Updating data of hospital branch")
    #         # get the resp json from redis
    #         await self.local_cache.update_drug_list_from_redis()
    #         await self.local_cache.update_drug_set_from_redis()
    #         await self.local_cache.update_code2info_from_redis()

    #         print("Finished updating hospital branch")
    #     except Exception as e:
    #         print("There is an error while handling the db sync")
    #         print(f'Message: {str(e)}')

    def update_machine(self):
        try:
            print("Updating data of hospital branch")
            # get the resp json from redis
            self.local_cache.update_drug_list_from_redis()
            self.local_cache.update_drug_set_from_redis()
            self.local_cache.update_code2info_from_redis()

            print("Finished updating hospital branch")
        except Exception as e:
            print("There is an error while handling the db sync")
            print(f'Message: {str(e)}')

    def listen_pub(self):
        while True:
            # print("waked up")
            hip_branch = "hip_branch"
            if hip_branch not in self.queue_elements:
                self.queue_elements.add(hip_branch)
                self.update_queue.put(hip_branch)
            sleep(0.1)

    def process_update_job(self, event_loop):
        asyncio.set_event_loop(event_loop)
        while True:
            try:
                hip_branch = self.update_queue.get()
                self.queue_elements.remove(hip_branch) # started acceptting new calls again
                # event_loop.run_until_complete(self.update_machine())
                self.update_machine()
                self.update_queue.task_done()
            except Exception as e:
                print(f'error_message {str(e)}')

# def sync_task():
#     print("task sync")
#     print("task sync")
#     redis_sync = redis.StrictRedis(host="redis", db=0)
#     # simulate 3 gets
#     for i in range(3):
#         value = redis_sync.get("test-key")
#     print("return from redis_sync.get")
#     print("return from redis_sync.get")

# async def async_task():
#     print("task async")
#     print("task async")
#     # get from redis
#     local_cache = DrugSyncHelper()
#     await asyncio.gather(
#         local_cache.update_drug_list_from_redis(),
#         local_cache.update_drug_set_from_redis(),
#         local_cache.update_code2info_from_redis())

#     # redis_async = StrictRedis(host="redis", db=0)
#     # simulate 3 gets
#     # for i in range(3):
#     #     value = await redis_async.get("test-key")
#     print("return from redis_async.get")
#     print("return from redis_async.get")

# def bg_task(event_loop):
#     asyncio.set_event_loop(event_loop)
#     while True:
#         print("start bg_task")
#         print("start bg_task")

#         event_loop.run_until_complete(async_task())

#         # async way to simulate drug sync
#         # callback = lambda: asyncio.ensure_future(async_task())
#         # event_loop.call_soon_threadsafe(callback)
#         # sync way to simulate drug sync
#         # sync_task()

#         print("end bg_task")
#         print("end bg_task")
#         sleep(1)

APP = None
def create_app(remote_resource=False, cache=True):
    """Create and configure an instance of the Flask application.

    Args:
        remote_resource (bool): Use remote resource yaml. Defaults to False.
        cache (bool): Use cached app if available. Defaults to True.

    Returns:
        object: Flask app
    """
    global APP

    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    app = Flask(__name__)
    CORS(app, supports_credentials=True)

    @app.route("/sync")
    def sync_request():
        print("request /sync")

        # simulate invoke triton
        response = requests.get('http://triton:8080/infer')
        # simulate access shared data
        drug_list_resp = DrugSyncHelper().drug_list_resp
        drug_sets = DrugSyncHelper().drug_sets
        code2info = DrugSyncHelper().code2info

        return str(response.json())

    @app.route("/async")
    async def async_request():
        print("request /async")

        # simulate invoke triton
        response = requests.get('http://triton:8080/infer')
        # simulate access shared data
        drug_list_resp = DrugSyncHelper().drug_list_resp
        drug_sets = DrugSyncHelper().drug_sets
        code2info = DrugSyncHelper().code2info

        return str(response.json())

    print('app created !')
    APP = app

    return app

def post_fork_init():
    # insert fake data to redis
    fake_data = "x" * 1024 * 1024
    redis_sync = redis.StrictRedis(host="redis", db=0)
    redis_sync.set("test-key", fake_data)

    # init first event loop for log
    loop = EventLoop().loop

    Subscriber()

if __name__ == "__main__":
    app = create_app()
    post_fork_init()
    app.run(debug=True, host='0.0.0.0', port=5000)
