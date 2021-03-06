import os
import os.path
import sys
import random
import time
import datetime
import collections
import socket
import pdb
sys.path.append("nao_libs2")
#sys.path.append("/Users/aditi/aldebaran-sdk-1.6.13-macosx-i386/lib")
#sys.path.append("nao_libs_1.14")

import naoqi
from naoqi import ALBroker
from naoqi import ALModule
from naoqi import ALProxy
from naoqi import ALBehavior

from tutorMotions import *

# import json
from profile_models import Question, Session
from breaks import take_break
from breaks import get_break_speech
import copy
import pickle

class TutoringSession:
    def __init__(self, host, port, goNao):
        self.host = host
        self.port = port
        self.goNao = goNao
        self.numHintRequests = 0
        self.numQuestions = 0
        self.numCorrect = 0
        self.numIncorrect = 0
        self.numRepeatHints = 0
        self.pid = -1
        self.sessionNum = -1
        self.expGroup = -1
        self.logFile = None

        # holds session data for 'this' user
        self.__current_question = None
        self.current_session = None  # will be initialized when START message parsed

    def log_answer(self,history,q_type,answer,correct):
        history.write("Type: %d, Answered: %s, %s\n"%(q_type,answer,correct))
        history.flush()

    def log_data(self,data,per,tot,cor):
        data.seek(0)
        data.truncate()
        data.write("%d\n"%per)
        data.write("%d\n"%tot)
        data.write("%d\n"%cor)

    def map_msg_type(self,msgType):
        fullType = msgType
        if msgType == 'Q':
            fullType = 'QUESTION'
        elif msgType == 'CA':
            fullType = 'CORRECT'
        elif msgType == 'IA':
            fullType = 'INCORRECT'
        elif msgType == 'LIA':
            fullType = 'LAST INCORRECT'
        elif msgType == 'H1':
            fullType = 'HINT 1'
        elif msgType == 'H2':
            fullType = 'HINT 2'
        elif msgType == 'H3':
            fullType = 'HINT 3'
        elif msgType == 'AH':
            fullType = 'AUTOMATIC HINT'
        elif msgType == 'DH':
            fullType = 'DENIED HINT'
        elif msgType == 'RS':
            fullType = 'ROBOT SPEECH'
        elif msgType == 'RA':
            fullType = 'ROBOT ACTION'
        return fullType

    def log_transaction(self,msgType,questionNum,otherInfo):
        if otherInfo == 'true':
            otherInfo = 'automatic'
        if otherInfo == 'false':
            otherInfo = ''

        transaction = self.pid + "," + self.expGroup + "," + str(self.sessionNum) + ","
        #transaction += str(datetime.datetime.now()) + ","
        transaction += str(int(round(time.time() * 1000))) + ","
        transaction += str(questionNum) + ","
        transaction += self.map_msg_type(msgType) + ","
        transaction += otherInfo #should only have something for some msgTypes
        self.logFile.write(transaction+"\n")
        self.logFile.flush()

        # IMPORTANT! Commenting this out temporarily
        # self.update_session(msgType, questionNum, otherInfo)

    def store_session(self, data):
        '''
        Appends session data to file for storage
        '''

        with open("data/"+"session_data_"+"P"+self.pid+"_E"+self.expGroup+".txt", 'wb') as outfile:
            pickle.dump(data, outfile)

        return


    def load_session(self, file_name):
        '''
        Loads (most recent) session data from file for user
        Returns data
        '''

        with open(file_name, 'rb') as data_file:
            data = pickle.load(data_file)

        self.current_session = data
        return


    def update_session(self, msgType, questionNum, otherInfo):
        '''
        Updates session data given interaction

        Returns take_break_message if break needs to be taken.
            Otherwise, returns an empty string
        '''

        english_msg_type = self.map_msg_type(msgType)
        if msgType == 'START':
            self.current_session = Session(pid=self.pid, session_num=self.sessionNum)
        elif msgType == 'LOAD':
            session_file_name = "data/"+"session_data_P"+self.pid+"_E"+self.expGroup+".txt"
            self.load_session(session_file_name)
        elif msgType == 'Q':
            #if the questionNum means difficulty level has changed, clear the questions in the current_session
            if questionNum == 220 or questionNum == 330: #hard-coded values for first question in difficulty level 2 and 3
                print "in update_session: changed to difficulty_level 2 or 3, clearing list of questions in session"
                j = 0
                length = len(self.current_session)
                while j < length:
                    del self.current_session[0]
                    j += 1
                #self.current_session = Session(pid=self.pid, session_num=self.sessionNum)    
            self.__current_question = Question(question_num=questionNum)
        elif msgType == 'CA':
            ms_question_time = int(otherInfo.split(';')[1])  # in milliseconds
            self.__current_question.correct(ms_android_time=ms_question_time)
            self.current_session.append(copy.deepcopy(self.__current_question))
            print "Question time (total time) in update_session: " + str(self.__current_question.total_time)
        elif msgType == 'IA':
            self.__current_question.incorrect(last=False)
        elif msgType == 'LIA':
            ms_question_time = int(otherInfo.split(';')[1])  # in milliseconds
            self.__current_question.incorrect(ms_android_time=ms_question_time, last=True)
            self.current_session.append(copy.deepcopy(self.__current_question))
        elif msgType == 'H1' or msgType == 'H2' or msgType == 'H3':
            self.__current_question.hint()
        elif msgType == 'AH':
            pass
        elif msgType == 'DH':
            pass
        elif msgType == 'RS':
            pass # = 'ROBOT SPEECH'
        elif msgType == 'RA':
            pass # = 'ROBOT ACTION'
        elif msgType == 'TIMEOUT':
            ms_question_time = int(otherInfo.split(';')[1])  # in milliseconds
            self.__current_question.timeout(ms_android_time=ms_question_time)
            self.current_session.append(copy.deepcopy(self.__current_question))
        else:
            print "update_session error: non-handled msgType"
            pass

        # send message of whether or not to take break if appropriate msgType
        # and correct experiment type
        take_break_message = ""  # message to be sent to Android
        break_trigger = False
        break_trigger_expl = ""  # explains why or why not break triggered
        if (msgType == 'CA' or msgType == 'LIA' or msgType == 'TIMEOUT'):
            if int(self.expGroup) == 2:  # Reward break
                (break_trigger, break_trigger_expl) = take_break(self.current_session, reward_break=True)
                if break_trigger:
                    take_break_message = "REWARD_BREAK"
            elif int(self.expGroup) == 3:  # Frustration break
                (break_trigger, break_trigger_expl) = take_break(self.current_session, reward_break=False)
                if break_trigger:
                    take_break_message = "FRUSTRATION_BREAK"
            else:
                pass

        if msgType == 'CA' or msgType == 'LIA' or msgType == 'TIMEOUT':
            print self.current_session

        if take_break_message in ["REWARD_BREAK", "FRUSTRATION_BREAK"]:
            other_info = (
                'break message: ' + str(take_break_message) + '| '
                'break type: ' + str(self.current_session.breaks[-1].b_type) + '| '
                'break super: ' + str(self.current_session.breaks[-1].b_super)
            )

            self.log_transaction('BREAK', -1, other_info)

        # store session after every update just in case of crash
        self.store_session(self.current_session)

        return take_break_message


    #def tutor(history, data, categ):
    def tutor(self,categ):
        i = 1
        new = True
        wrong = []
        per = []
        tot = []
        cor = []
        print "num categories:", categ

        #then set up server connection for tablet to make connection
        BUFFER_SIZE = 1024  # Normally 1024, but we want fast response
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(1)
        print 'Waiting for client connection...'

        try:
            conn, addr = s.accept()
            print 'Connection address:', addr
            msg = conn.recv(BUFFER_SIZE)
            print msg
        except KeyboardInterrupt:
            sys.exit()

        sessionEnded = False
        while 1:
            try:
                msg = conn.recv(BUFFER_SIZE)
                if not msg: break
                print "received msg:", msg

                #in case multiple messages got sent, split by \n
                msg = msg.split('\n')
                while '' in msg:
                    msg.remove('')

                print 'between received msg and msg line is'
                for line in msg:
                    print "msg line is: ", line
                    #parse message type to know what to do with it
                    msgType = line.split(";",4)[0]
                    questionNum = int(line.split(";",2)[1]) #remove +1 since we are logging questionID in breaks study
                    questionType = line.split(";",4)[2].strip()
                    robot_speech = line.split(";",4)[3]
                    otherInfo = ''
                    id = -1
                    introFlag = False
                    returnMessage = "DONE"
                    print 'split line in msg'

                    robot_speech = robot_speech.replace("'","").strip()
                    if self.goNao is None:
                        robot_speech = robot_speech.replace("/", " over ").strip()
                    #robot_speech = "What does " + robot_speech + " equal?"

                    if msgType == 'START' or msgType == 'LOAD': #starting session
                        info = robot_speech.split(",")
                        self.pid = info[0]
                        self.sessionNum = info[1]
                        self.expGroup = info[2].strip()
                        fileString = "data/"+"P"+self.pid+"_E"+self.expGroup+".txt"
                        print fileString
                        if os.path.exists(fileString):
                            self.logFile = open(fileString, "a")
                        else:
                            self.logFile = open(fileString, "w")
                        self.logFile.write("PARTICIPANT_ID,EXP_GROUP,SESSION_NUM,TIMESTAMP,QUESTION_NUM,TYPE,OTHER_INFO\n");

                        #do intro depending on the sessionNum
                        if self.goNao is not None and msgType != 'LOAD':
                            introFlag = True
                            id = self.goNao.intro() #new intro for breaks study #ADD BACK IN, COMMENTED OUT FOR TESTING
                            # id = self.goNao.session_intro(int(self.sessionNum))  #DANGER 

                        #create or load appropriate session object
                        self.update_session(msgType, questionNum, "")

                    elif msgType == 'Q': #question
                        self.numQuestions += 1
                        otherInfo = line.split(";",4)[4].strip()
                        returnMessage = otherInfo
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            #self.goNao.assessQuestion(questionType)
                            #id = self.goNao.genSpeech(robot_speech)
                            #[id,speech] = self.goNao.introQuestion(robot_speech)
                            [id,speech] = self.goNao.introQuestionGeneric() #changing for breaks study problems
                            self.log_transaction("RS",questionNum,speech)
                            rand_choice = random.randint(0,3)
                            point = "no_point"
                            if(rand_choice == 1):
                                #id = self.goNao.genSpeech("Here it is.")
                                self.goNao.point_question()
                                point = "point_to_question"
                                self.log_transaction("RA",questionNum,point)
                            #self.goNao.assessQuestion(questionType) #dont need for break study
                        self.update_session(msgType, questionNum, otherInfo)
                    elif msgType == 'CA': #correct attempt
                        self.numCorrect += 1
                        otherInfo = line.split(";",4)[4].strip()

                        questionTime = line.split(";",5)[5].strip()  # DANGER maybe do something with this

                        print "Question time in app: " + str(questionTime)  # DANGER DEBUGGING

                        print 'correct answer'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            #self.goNao.juddNelson()
                            [id,speech] = self.goNao.assess("correct")
                            self.log_transaction("RS",questionNum,speech)
                            #pump = "no_pump"
                            #rand_choice = random.randint(0,3)
                            #if(rand_choice == 1):
                            #    self.goNao.juddNelson()
                            #    pump = "right_pump"
                            #elif(rand_choice == 2):
                            #    self.goNao.juddNelson_left()
                            #    pump = "left_pump"
                            #self.log_transaction("RA",questionNum,pump) 
                            #self.goNao.sit()
                        tempMessage = self.update_session(msgType, questionNum, otherInfo)
                        if tempMessage:  # if not empty string, then return message should indicate break
                            returnMessage = tempMessage
                        
                    elif msgType == 'IA': #incorrect attempt
                        self.numIncorrect += 1
                        otherInfo = line.split(";",4)[4].strip()
                        print 'incorrect answer'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            if otherInfo.find("/")!=-1:
                                num = otherInfo.split("/")[0]
                                denom = otherInfo.split("/")[1]
                                if int(num)==0 or int(denom)==0:
                                    robot_speech = robot_speech.replace("/", " over ").strip()
                            self.goNao.look()
                            self.goNao.genSpeech(robot_speech)
                            [id,speech] = self.goNao.assess("wrong")
                            self.log_transaction("RS",questionNum,speech)
                            self.goNao.shake()
                            #self.goNao.sit()
                    elif msgType == 'LIA': #incorrect attempt
                        self.numIncorrect += 1
                        otherInfo = line.split(";",4)[4].strip()

                        questionTime = line.split(";",5)[5].strip()  # DANGER maybe do something with this

                        print "Question time in app: " + str(questionTime)  # DANGER DEBUGGING

                        print 'incorrect answer (last attempt)'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            id = self.goNao.genSpeech(robot_speech)
                            #self.goNao.last_shake()
                            #self.goNao.sit()
                        tempMessage = self.update_session(msgType, questionNum, otherInfo)
                        if tempMessage:  # if not empty string, then return message should indicate break
                            returnMessage = tempMessage
                    elif msgType == 'H1': #hint request
                        self.numHintRequests += 1
                        otherInfo = line.split(";",4)[4].strip()
                        print 'hint 1 request'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            if otherInfo == 'true':
                                speech = self.goNao.assess("auto_hint")[1]
                                self.log_transaction("RS",questionNum,speech)
                            id = self.goNao.genSpeech(robot_speech)
                            #self.goNao.sit()
                    elif msgType == 'H2': #hint request
                        self.numHintRequests += 1
                        otherInfo = line.split(";",4)[4].strip()
                        print 'hint 2 request'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            if otherInfo == 'true':
                                speech = self.goNao.assess("auto_hint")[1]
                                self.log_transaction("RS",questionNum,speech)
                            id = self.goNao.genSpeech(robot_speech)
                            self.goNao.assessHint2(questionType)
                            #self.goNao.sit()
                    elif msgType == 'H3': #hint request
                        self.numHintRequests += 1
                        otherInfo = line.split(";",4)[4].strip()
                        print 'hint 3 request'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            #self.goNao.assessHint(questionType)
                            if otherInfo == 'true':
                                speech = self.goNao.assess("auto_hint")[1]
                                self.log_transaction("RS",questionNum,speech)
                            id = self.goNao.genSpeech(robot_speech)
                            self.goNao.assessHint3(questionType)
                            #self.goNao.sit()               
                    elif msgType == 'AH': #automatic hint triggered
                        print 'automatic hint triggered'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            id = self.goNao.genSpeech(robot_speech)
                            #self.goNao.sit()
                    elif msgType == 'DH': #denied hint
                        self.numHintRequests += 1 #do we want to do this?
                        otherInfo = line.split(";",4)[4].strip()
                        print 'hint request denied'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            id = self.goNao.genSpeech(robot_speech)
                            #self.goNao.sit()           
                    elif msgType == 'END': #session ended
                        print 'tutoring session ended'
                        sessionEnded = True
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            id = self.goNao.genSpeech(robot_speech)
                            self.goNao.congratulations()
                            #self.goNao.sit()   
                        #break

                    elif msgType.startswith('LESSON'):
                        otherInfo = line.split(";",4)[4].strip()
                        id, otherInfo = self.handle_lesson_msg(msgType, robot_speech, otherInfo)
                        returnMessage = msgType

                    elif msgType.startswith('TICTACTOE'):
                        id, otherInfo = self.handle_tictactoe_msg(msgType, robot_speech)
                        returnMessage = msgType

                    elif msgType.startswith('STRETCHBREAK'):
                        id, otherInfo = self.handle_stretch_break_msg(msgType, robot_speech)
                        if msgType == 'STRETCHBREAK-START':
                            msgType = 'STRETCHBREAK-DONE'
                            otherInfo = ' '
                        returnMessage = 'STRETCHBREAK-DONE'

                    elif msgType.startswith('VISUALFOCUS'):
                        print 'made it into msgType starts with visualfocus'
                        id, otherInfo = self.handle_visualfocus_msg(msgType, robot_speech)
                        returnMessage = msgType

                    elif msgType.startswith('MINDFULNESSBREAK'):
                        id, otherInfo = self.handle_mindfulness_break_msg(msgType, robot_speech)
                        if msgType == 'MINDFULNESSBREAK-START':
                            msgType = 'MINDFULNESSBREAK-DONE'
                            otherInfo = ' '
                        returnMessage = 'MINDFULNESSBREAK-DONE'    

                    elif msgType.startswith('TIMEOUT'):
                        id = self.handle_timeout_msg(msgType, robot_speech)
                        otherInfo = line.split(";",4)[4].strip()
                        tempMessage = self.update_session(msgType, questionNum, otherInfo)
                        if tempMessage: # if not empty string, then return message should indicate break
                            returnMessage = tempMessage
                    else:
                        print 'error: unknown message type'

                    if self.goNao is not None: #should we check that id != -1
                        if id != -1:
                            self.goNao.speechDevice.wait(id, 0)
                            if introFlag is not True:
                                self.goNao.sit()
                                conn.send(returnMessage+"\n")
                                print 'send tablet message that robot is done (or a REWARD_BREAK/FRUSTRATION_BREAK message!)'
                    else: #case just for testing without robot
                        time.sleep(2)
                        conn.send(returnMessage+"\n")
                    self.log_transaction(msgType,questionNum,otherInfo)
                if sessionEnded:
                    self.logFile.close()
                    self.store_session(self.current_session)
                    break
            except KeyboardInterrupt:
                self.logFile.flush()
                self.logFile.close()
                conn.close()
                self.store_session(self.current_session)
                sys.exit(0)


    def handle_timeout_msg(self, msg_type, robot_speech):
        speech_return = 0
        if self.goNao is None:
            os.system('say ' + robot_speech)
        else:
            speech_return = self.goNao.genSpeech(robot_speech)
        return speech_return


    def handle_lesson_msg(self, msg_type, robot_speech, otherInfo):
        speech_return = 0
        msg_sub_type = msg_type[7:]
        
        if self.goNao is None:
            os.system('say ' + robot_speech)
            if otherInfo == 'nothing':
                return speech_return, robot_speech
            else:
                self.log_transaction("RS",-1,robot_speech)
                return speech_return, otherInfo
        else:
            if msg_sub_type == 'PART1' or msg_sub_type == 'PART6':
                self.goNao.look()
                first_half = robot_speech.split("!",1)[0].strip() + "!"
                second_half = robot_speech.split("!",1)[1].strip()
                id = self.goNao.genSpeech(first_half)
                self.goNao.speechDevice.wait(id, 0)
                self.goNao.sit()
                speech_return = self.goNao.genSpeech(second_half)
            elif msg_sub_type == 'PART3' or msg_sub_type == 'PART8':
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)
                self.goNao.point_question()   
            else:    
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)
            
            if otherInfo == 'nothing':
                return speech_return, robot_speech
            else:
                self.log_transaction("RS",-1,robot_speech)
                return speech_return, otherInfo

        


    def handle_tictactoe_msg(self, msg_type, robot_speech):
        speech_return = 0
        msg_sub_type = msg_type[10:]

        if msg_sub_type == 'START':
            # <robot_speech> won't be sent from the tablet in this case. Because the robot's speech
            # needs to be modified depending on the reason that the break was triggered, the speech
            # will be constructed here.
            robot_speech_base = (
                "Lets play a game of tic-tac-toe. You will be exes, and I will be ohs. You can "
                "go first. Click any square on the board."
            )
            if int(self.expGroup) == 1:
                robot_speech = get_break_speech(1, -1, -1) + " " + robot_speech_base
            else:
                robot_speech = get_break_speech(
                    int(self.expGroup),
                    self.current_session.breaks[-1].b_super,
                    self.current_session.breaks[-1].b_type
                ) + " " + robot_speech_base

            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'WIN':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'TIE':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'LOSS':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'NAOTURN':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'STUDENTTURN':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'RESTART':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'END':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        return speech_return, robot_speech


    def handle_stretch_break_msg(self, msg_type, robot_speech):
        speech_return = 0
        msg_sub_type = msg_type[13:]

        if msg_sub_type == 'START':
            # <robot_speech> won't be sent from the tablet in this case. Because the robot's speech
            # needs to be modified depending on the reason that the break was triggered, the speech
            # will be constructed here.
            robot_speech_base = "Lets stretch."
            if int(self.expGroup) == 1:
                robot_speech = get_break_speech(1, -1, -1) + " " + robot_speech_base
            else:
                robot_speech = get_break_speech(
                    int(self.expGroup),
                    self.current_session.breaks[-1].b_super,
                    self.current_session.breaks[-1].b_type
                ) + " " + robot_speech_base

            self.log_transaction('STRETCHBREAK-START', -1, robot_speech)
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)
                self.goNao.stretchBreak()

        return speech_return, robot_speech

    def handle_visualfocus_msg(self, msg_type, robot_speech):
        speech_return = 0
        msg_sub_type = msg_type[12:]
        print 'got into handle_visualfocus_msg'

        if msg_sub_type == 'START':
            print 'into start block, happens once'
            #TODO: properly fill out robot speech to start the break here, depending on the expGroup
            robot_speech_base = "Lets play a. focus game. Press the button that is different from the rest! "
            if int(self.expGroup) == 1:
                robot_speech = get_break_speech(1, -1, -1) + " " + robot_speech_base
            else:
                robot_speech = get_break_speech(
                    int(self.expGroup),
                    self.current_session.breaks[-1].b_super,
                    self.current_session.breaks[-1].b_type
                ) + " " + robot_speech_base

            print 'before log_transaction'
            #self.log_transaction('VISUALFOCUS-START', 0, robot_speech)
            print 'after log_transaction'
            if self.goNao is None:
                print 'before os call'
                os.system('say ' + robot_speech)
                print 'after os call'
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)
        
        elif msg_sub_type == 'ROUNDOVER' or msg_sub_type == 'END':
            #self.log_transaction('VISUALFOCUS-ROUNDOVER', 0, robot_speech)
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'RESTART':
            #self.log_transaction('VISUALFOCUS-ROUNDOVER', 0, robot_speech)
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)                

        return speech_return, robot_speech

    def handle_mindfulness_break_msg(self, msg_type, robot_speech):
        speech_return = 0
        msg_sub_type = msg_type[17:]

        if msg_sub_type == 'START':
            #TODO: properly fill out robot speech to start the break here, including "lets relax."
            robot_speech_base = "Lets do a small exercise to relax."
            if int(self.expGroup) == 1:
                robot_speech = get_break_speech(1, -1, -1) + " " + robot_speech_base
            else:
                robot_speech = get_break_speech(
                    int(self.expGroup),
                    self.current_session.breaks[-1].b_super,
                    self.current_session.breaks[-1].b_type
                ) + " " + robot_speech_base
            self.log_transaction('MINDFULNESSBREAK-START', -1, robot_speech)
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                self.goNao.look()
                speech_return = self.goNao.genSpeech(robot_speech)
                self.goNao.mindfulnessBreak()

        return speech_return, robot_speech



        """
        for j in range(categ):
            wrong.append(0)
            if not data[j].readline():
                per.append(100)
                tot.append(0)
                cor.append(0)
            else:
                data[j].seek(0)
                per.append(int(data[j].readline()))
                tot.append(int(data[j].readline()))
                cor.append(int(data[j].readline()))

        #Anthony's question/answer parsing code - take parts from this and move it above
        while 1:
            msg = s.recv(BUFFER_SIZE)
            if not msg:
                break
            if (msg == "exit"):
                break
            q_type, help, answer, human_choice = msg.split(' ')
            q_type = int(q_type)
            help = int(help)
            answer = int(answer)
            human_choice = int(human_choice)

            correct = False
            tot[q_type] += 1

            if human_choice == answer:
                correct = True
                wrong[q_type] = 0
                cor[q_type] += 1
                goNao.assess("correct")

            elif help:
                tot[q_type] -= 1
                per[q_type] = (float(cor[q_type])/float(tot[q_type])) * 100
                
                if per[q_type] > 70:
                    goNao.genSpeech("I think you can do it. Try to answer.")
                
                else:
                    goNao.assess("hint")
            
            else:
                per[q_type] = (float(cor[q_type])/float(tot[q_type])) * 100
                wrong[q_type] = wrong[q_type] + 1
                
                if wrong[q_type] > 4:
                    goNao.assess("trouble")
                    break_choice = raw_input("Take a break? y for yes, n for no: ")
                    if break_choice is "y":
                        goNao.genSpeech("I have a fun game for you.")
                        time.sleep(60) # play a game
                        goNao.genSpeech("That was fun! Now let's get back to work.")
                
                elif per[q_type] < 70 and tot[q_type] > 10:
                    goNao.assess("hint")
                    hint_choice = raw_input("Would you like a hint? y for yes, n for no: ")
                    if hint_choice is "y":
                        goNao.genSpeech("I think I can help")
                        # give a hint

                elif per[q_type] > 70 and tot[q_type] > 10:
                    goNao.assess("confused")
                
                else:
                    goNao.assess("wrong")

            log_answer(history,q_type,human_choice,correct)
        
        for i in range(categ):
            if tot[i] is not 0:
                per[i] = (float(cor[i])/float(tot[i])) * 100
            log_data(data[i],per[i],tot[i],cor[i])
        
        goNao.goodbye()
        """


def main():
    #start main piece of nao tutoring interaction
    NAO_PORT = 9559
    useRobot = False
    if len(sys.argv) >= 3:
        TCP_IP = sys.argv[1]
        TCP_PORT = int(sys.argv[2])
        if len(sys.argv) == 4:
            if sys.argv[3]=='-robot':
                useRobot = True
    
    if useRobot:
        #Get the Nao's IP from file
        try:
            ipFile = open("ip.txt")
            NAO_IP = ipFile.readline().replace("\n","").replace("\r","")
        except Exception as e:
            print "Could not open file ip.txt"
            NAO_IP = raw_input("Please write Nao's IP address. ") 
    print 'ip and port:', TCP_IP, TCP_PORT
    #print 'nao ip:', NAO_IP


    #first connect to the NAO if -robot flag is set
    goNao = None
    if useRobot:
        try:
            print 'trying to connect nao\n'
            goNao = Gesture(NAO_IP, NAO_PORT)
        except Exception as e:
            print "Could not find nao. Check that your ip is correct (%s)" %TCP_IP
            sys.exit()


        #Set postureProxy
        try:
            postureProxy = ALProxy("ALRobotPosture", NAO_IP, NAO_PORT)
        except Exception, e:
            print "Could not create proxy to ALRobotPosture"
            print "Error was: ", e

        motionProxy = ALProxy("ALMotion", NAO_IP, NAO_PORT)


    ongoing = True

    while ongoing:
        #Choose an action
        #Set all the possible commands
        commands=collections.OrderedDict((("i", "Run the intro"),
        ("r", "Release motors"),
        ("break", "break for pdb"),
        ("t", "Type something for the nao to say"),
        ("m", "Move nao head - test"),
        ("w", "Wave arm"),
        ("f", "Fist of triumph for correct answer"),
        ("g", "Right fist of triumph for correct answer"),
        #("n", "Nod for correct answer"),
        ("a", "Shake for incorrect answer"),
        ("u", "Scale up"),
        ("d", "Scale down"),
        ("p", "Adding and subtracting problems"),
        ("k", "While talking"),
        ("l", "Idle behavior"),
        ("x", "Relaxed idle behavior left"),
        ("y", "Relaxed idle behavior right"),
        ("n", "Numerator"),
        ("e", "Denominator"),
        ("bi", "breathe in guide"),
        ("bo", "breathe out guide"),
        ("o", "And so on"),
        ("c", "Conversion problems"),
        ("z", "Congratulations!"),
        ("b", "Stretch break"),
        ("mind", "Mindfulness break"),
        ("s", "Start tutoring interaction"),
        ("q", "Quit"),
        ))


        #Output all the commands
        print "\nPlease choose an action:"
        for key,value in commands.items():
            print("\t%s => %s"%(key,value))

        #Have the user select the choice
        choice = ""
        if choice not in commands:
            choice = raw_input('Choice: ').replace("\n","").replace("\r","")


        #Execute the user's choice
        if(choice == "i"):
            #postureProxy.goToPosture("Stand", 1.0)
            #print 'nao is sitting'
            #motionProxy.setBreathEnabled('Body', True)
            #print 'nao is breathing'
            #time.sleep(10) 
            #goNao.intro()
            goNao.intro()

        elif(choice=="r"):
            goNao.releaseNao()
        elif(choice=="break"):
            pdb.set_trace()
        elif(choice == "t"):
            phrase = raw_input('Type phrase here: ')
            goNao.genSpeech(phrase)
            #history = open("data/Tony.txt","a")
            #tutor(history)

        elif(choice == "m"):
            goNao.move_head()

        elif(choice == "w"):
            goNao.wave()

        elif(choice == "f"):
            goNao.juddNelson()

        elif(choice == "g"):
            goNao.juddNelson_left()

        #elif(choice == 'n'):
        #   goNao.nod()

        elif(choice == "a"):
            goNao.shake()

        elif(choice == "u"):
            goNao.scale_up()

        elif(choice == "d"):
            goNao.scale_down()

        elif(choice == "p"):
            goNao.two_fractions()

        elif(choice == "k"):
            goNao.look()

        elif(choice == "l"):
            goNao.sit()

        elif(choice == "x"):
            goNao.left_relaxed_sit()

        elif(choice == "y"):
            goNao.right_relaxed_sit()

        elif(choice == "n"):
            goNao.numerator()

        elif(choice == "e"):
            goNao.denominator()

        elif(choice == "bi"):
            goNao.breathe_in_guide()

        elif(choice == "bo"):
            goNao.breathe_out_guide()    

        elif(choice == "o"):
            goNao.etc()

        elif(choice == "c"):
            goNao.conversion()

        elif(choice == "z"):
            goNao.congratulations()

        elif(choice == "b"):
            goNao.stretchBreak()
        elif(choice == "mind"):
            goNao.mindfulnessBreak()    

        #elif(choice == 'o'):
        #   goNao.tilt()

        #elif(choice == 'h'):
        #   goNao.hands()

        #elif(choice == 'b'):
        #   goNao.breathe()

        elif(choice == "s"):
            if useRobot:
                postureProxy.goToPosture("Sit", 0.5)
            session = TutoringSession(TCP_IP, TCP_PORT, goNao)
            with open('topics.txt') as f:
                categ = sum(1 for _ in f)
            session.tutor(categ)

        elif(choice == "q"):
            ongoing = False
        """
        participant_name = raw_input('Input participant\'s name: ').replace("\n","").replace("\r","")
        
        with open('topics.txt') as f:
            categ = sum(1 for _ in f)
        if categ != 2:
            print "Error"
            exit()

        data = []
        
        if os.path.exists("data_TCP/%s.txt"%participant_name):
            history = open("data_TCP/%s.txt"%participant_name,"a")
        
        else:
            history = open("data_TCP/%s.txt"%participant_name,"a")
            history.write("%s\n"%participant_name)
            for i in range(categ):
                open("data_TCP/%s_%d.txt"%(participant_name,i),"w")
        
        history.write("------------\n")
        today = datetime.datetime.now()
        history.write("%s\n" % today)
        history.flush()

        for i in range(categ):
            data.append(open("data_TCP/%s_%d.txt"%(participant_name,i),"r+"))

        #goNao.intro()
        postureProxy.goToPosture("SitRelax", 1.0)

        goNao.genSpeech("Shall we get started, %s?"%participant_name)
        time.sleep(2)

        tutor(history, data, categ)
        postureProxy.goToPosture("SitRelax", 1.0)

        goNao.releaseNao()
        history.write("\n")
        history.close()
        """

if __name__ == "__main__": 
    main()

