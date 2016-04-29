import os
import os.path
import sys
import random
import time
import datetime
import collections
import socket
sys.path.append("nao_libs")
#sys.path.append("/Users/aditi/aldebaran-sdk-1.6.13-macosx-i386/lib")
#sys.path.append("nao_libs_1.14")

import naoqi
from naoqi import ALBroker
from naoqi import ALModule
from naoqi import ALProxy
from naoqi import ALBehavior

from tutorMotions import *

import json
from profile_models import Question, Session
import copy

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

        transaction = self.pid + "," + self.expGroup + "," + self.sessionNum + ","
        transaction += str(datetime.datetime.now()) + ","
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

        with open('sample_person_data.txt', 'a') as outfile:
            json.dump(data, outfile)

        return


    def load_session(self, data):
        '''
        Loads (most recent) session data from file for user
        Returns data
        '''

        with open('data.json') as data_file:
            data = json.load(data_file)

        return data


    def update_session(self, msgType, questionNum, otherInfo):
        '''
        Updates session data given interaction
        '''
        question_data = {}
        english_msg_type = self.map_msg_type(msgType)
        if msgType == 'Q':
            self.__current_question = Question(question_num=questionNum)
        elif msgType == 'CA':
            self.__current_question.correct()
            self.current_session.append(copy.deepcopy(self.__current_question))
        elif msgType == 'IA':
            self.__current_question.incorrect(last=False)
        elif msgType == 'LIA':
            self.__current_question.incorrect(last=True)
            self.current_session.append(copy.deepcopy(self.__current_question))
        elif msgType == 'H1' or msgType == 'H2' or msgType == 'H3':
            self.__current_question.hint()
        elif msgType == 'AH':
            __special(msgType) # = 'AUTOMATIC HINT'
        elif msgType == 'DH':
            __special(msgType) # = 'DENIED HINT'
        elif msgType == 'RS':
            pass # = 'ROBOT SPEECH'
        elif msgType == 'RA':
            pass # = 'ROBOT ACTION'
        else:
            pass
        self.session[questionNum] = {}


        return


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

                for line in msg:
                    print "msg line is: ", line
                    #parse message type to know what to do with it
                    msgType = line.split(";",4)[0]
                    questionNum = int(line.split(";",2)[1])+1
                    questionType = line.split(";",4)[2].strip()
                    robot_speech = line.split(";",4)[3]
                    otherInfo = ''
                    id = -1
                    introFlag = False
                    returnMessage = "DONE"

                    robot_speech = robot_speech.replace("'","").strip()
                    if self.goNao is None:
                        robot_speech = robot_speech.replace("/", " over ").strip()
                    #robot_speech = "What does " + robot_speech + " equal?"

                    if msgType == 'START': #starting session
                        info = robot_speech.split(",")
                        self.pid = info[0]
                        self.sessionNum = info[1]
                        self.expGroup = info[2].strip()
                        fileString = "data/"+"P"+self.pid+"_S"+self.sessionNum+".txt"
                        print fileString
                        if os.path.exists(fileString):
                            self.logFile = open(fileString, "a")
                        else:
                            self.logFile = open(fileString, "w")
                        self.logFile.write("PARTICIPANT_ID,EXP_GROUP,SESSION_NUM,TIMESTAMP,QUESTION_NUM,TYPE,OTHER_INFO\n");

                        #do intro depending on the sessionNum
                        if self.goNao is not None:
                            introFlag = True
                            id = self.goNao.session_intro(int(self.sessionNum))

                        #create appropriate session object
                        # IMPORTANT! Commenting this out temporarily
                        # self.current_session = Session(pid=self.pid, sessionNum=self.sessionNum)

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
                            [id,speech] = self.goNao.introQuestion(robot_speech)
                            self.log_transaction("RS",questionNum,speech)
                            self.goNao.assessQuestion(questionType) 
                    elif msgType == 'CA': #correct attempt
                        self.numCorrect += 1
                        otherInfo = line.split(";",4)[4].strip()
                        print 'correct answer' 
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            #self.goNao.juddNelson()
                            [id,speech] = self.goNao.assess("correct")
                            self.log_transaction("RS",questionNum,speech)
                            pump = "no_pump"
                            rand_choice = random.randint(0,3)
                            if(rand_choice == 1):
                                self.goNao.juddNelson()
                                pump = "right_pump"
                            elif(rand_choice == 2):
                                self.goNao.juddNelson_left()
                                pump = "left_pump"
                            self.log_transaction("RA",questionNum,pump) 
                            #self.goNao.sit()
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
                        print 'incorrect answer (last attempt)'
                        if self.goNao is None:
                            os.system("say " + robot_speech)
                        else:
                            self.goNao.look()
                            id = self.goNao.genSpeech(robot_speech)
                            #self.goNao.last_shake()
                            #self.goNao.sit()       
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
                    elif msgType.startswith('TICTACTOE'):
                        id = self.handle_tictactoe_msg(msgType, robot_speech)
                        returnMessage = msgType
                    else:
                        print 'error: unknown message type'

                    if self.goNao is not None: #should we check that id != -1
                        if id != -1:
                            self.goNao.speechDevice.wait(id, 0)
                            if introFlag is not True:
                                self.goNao.sit()
                                conn.send(returnMessage+"\n")
                                print 'send tablet message that robot is done'
                    else: #case just for testing without robot
                        time.sleep(2)
                        conn.send(returnMessage+"\n")
                    self.log_transaction(msgType,questionNum,otherInfo)
                if sessionEnded:
                    self.logFile.close()
                    break
            except KeyboardInterrupt:
                self.logFile.flush()
                self.logFile.close()
                conn.close()
                sys.exit(0)


    def handle_tictactoe_msg(self, msg_type, robot_speech):
        speech_return = 0
        msg_sub_type = msg_type[10:]

        if msg_sub_type == 'START':
            print 'Tic-tac-toe: Started'
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'WIN':
            print 'Tic-tac-toe: Student won'
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'TIE':
            print 'Tic-tac-toe: Student and robot tied'
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'LOSS':
            print 'Tic-tac-toe: Student lost'
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'NAOTURN':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'STUDENTTURN':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'RESTART':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)

        elif msg_sub_type == 'END':
            if self.goNao is None:
                os.system('say ' + robot_speech)
            else:
                speech_return = self.goNao.genSpeech(robot_speech)

        return speech_return


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
        ("t", "Type something for the nao to say"),
        ("m", "Move nao head - test"),
        ("w", "Wave arm"),
        ("f", "Fist of triumph for correct answer"),
        ("g", "Right fist of triumph for correct answer"),
        #("n", "Nod for correct answer"),
        ("a", "Shake for incorrect answer"),
        #("o", "Head off to the side for thinking"),
        #("h", "Hands together for thinking"),
        #("b", "Stand up and try to breathe"),
        ("u", "Scale up"),
        ("d", "Scale down"),
        ("p", "Adding and subtracting problems"),
        ("k", "While talking"),
        ("l", "Idle behavior"),
        ("x", "Relaxed idle behavior left"),
        ("y", "Relaxed idle behavior right"),
        ("n", "Numerator"),
        ("e", "Denominator"),
        ("o", "And so on"),
        ("c", "Conversion problems"),
        ("z", "Congratulations!"),
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

        elif(choice == "o"):
            goNao.etc()

        elif(choice == "c"):
            goNao.conversion()

        elif(choice == "z"):
            goNao.congratulations()

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

