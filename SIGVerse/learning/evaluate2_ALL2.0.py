#coding:utf-8
#TCDS2の評価用プログラムを流用、改造したSpCoSLAM用評価プログラム（基本的にこれを使う）
#ARI(0埋め),NMI（0埋め）,PARw（MI重みづけあり）,PARw(MI重みづけなし),L,K,分割単語数、PARｓ
#PAR_W_MIがPARsとして保存されていたものを修正
#Akira Taniguchi 
#2017/02/13-2017/02/25-2018/01/25
import sys
import os.path
import random
import string
import collections
import numpy as np
from numpy.linalg import inv, cholesky
from scipy.stats import chi2
from math import pi as PI
from math import cos,sin,sqrt,exp,log,fabs,fsum,degrees,radians,atan2
from sklearn.metrics.cluster import adjusted_rand_score
from sklearn.metrics.cluster import normalized_mutual_info_score
from __init__ import *

#相互推定のイテレーションごとに選ばれた学習結果の評価値（ARI、コーパスPAR、単語PAR）、（事後確率値）を出力
##単語PARはp(O_best|x_t)と正解を比較。x_tは正しいデータの平均値とする。

step = data_step_num

def gaussian(x,myu,sig):
    ###1次元ガウス分布
    gauss = (1.0 / sqrt(2.0*PI*sig*sig)) * exp(-1.0*(float((x-myu)*(x-myu))/(2.0*sig*sig)))
    return gauss
    
def gaussian2d(Xx,Xy,myux,myuy,sigma):
    ###ガウス分布(2次元)
    sqrt_inb = float(1) / ( 2.0 * PI * sqrt( np.linalg.det(sigma)) )
    xy_myu = np.array( [ [float(Xx - myux)],[float(Xy - myuy)] ] )
    dist = np.dot(np.transpose(xy_myu),np.linalg.solve(sigma,xy_myu))
    gauss2d = (sqrt_inb) * exp( float(-1/2) * dist )
    return gauss2d

def fill_param(param, default):   ##パラメータをNone の場合のみデフォルト値に差し替える関数
    if (param == None): return default
    else: return param

def invwishartrand_prec(nu,W):
    return inv(wishartrand(nu,W))

def invwishartrand(nu, W):
    return inv(wishartrand(nu, inv(W)))

def wishartrand(nu, W):
    dim = W.shape[0]
    chol = cholesky(W)
    #nu = nu+dim - 1
    #nu = nu + 1 - np.axrange(1,dim+1)
    foo = np.zeros((dim,dim))
    
    for i in xrange(dim):
        for j in xrange(i+1):
            if i == j:
                foo[i,j] = np.sqrt(chi2.rvs(nu-(i+1)+1))
            else:
                foo[i,j]  = np.random.normal(0,1)
    return np.dot(chol, np.dot(foo, np.dot(foo.T, chol.T)))
    
class NormalInverseWishartDistribution(object):
#http://stats.stackexchange.com/questions/78177/posterior-covariance-of-normal-inverse-wishart-not-converging-properly
    def __init__(self, mu, lmbda, nu, psi):
        self.mu = mu
        self.lmbda = float(lmbda)
        self.nu = nu
        self.psi = psi
        self.inv_psi = np.linalg.inv(psi)

    def particle(self):
        sigma = np.linalg.inv(self.wishartrand())
        return (np.random.multivariate_normal(self.mu, sigma / self.lmbda), sigma)

    def wishartrand(self):
        dim = self.inv_psi.shape[0]
        chol = np.linalg.cholesky(self.inv_psi)
        foo = np.zeros((dim,dim))
        
        for i in range(dim):
            for j in range(i+1):
                if i == j:
                    foo[i,j] = np.sqrt(chi2.rvs(self.nu-(i+1)+1))
                else:
                    foo[i,j]  = np.random.normal(0,1)
        return np.dot(chol, np.dot(foo, np.dot(foo.T, chol.T)))

    def posterior(self, data):
        n = len(data)
        mean_data = np.mean(data, axis=0)
        sum_squares = np.sum([np.array(np.matrix(x - mean_data).T * np.matrix(x - mean_data)) for x in data], axis=0)
        mu_n = (self.lmbda * self.mu + n * mean_data) / (self.lmbda + n)
        lmbda_n = self.lmbda + n
        nu_n = self.nu + n
        psi_n = self.psi + sum_squares + self.lmbda * n / float(self.lmbda + n) * np.array(np.matrix(mean_data - self.mu).T * np.matrix(mean_data - self.mu))
        return NormalInverseWishartDistribution(mu_n, lmbda_n, nu_n, psi_n)

def levenshtein_distance(a, b):
    m = [ [0] * (len(b) + 1) for i in range(len(a) + 1) ]

    for i in xrange(len(a) + 1):
        m[i][0] = i

    for j in xrange(len(b) + 1):
        m[0][j] = j

    for i in xrange(1, len(a) + 1):
        for j in xrange(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                x = 0
            else:
                x = 1
            m[i][j] = min(m[i - 1][j] + 1, m[i][ j - 1] + 1, m[i - 1][j - 1] + x)
    # print m
    return m[-1][-1]
    

#http://nbviewer.ipython.org/github/fonnesbeck/Bios366/blob/master/notebooks/Section5_2-Dirichlet-Processes.ipynb
def stick_breaking(alpha, k):
    betas = np.random.beta(1, alpha, k)
    remaining_pieces = np.append(1, np.cumprod(1 - betas[:-1]))
    p = betas * remaining_pieces
    return p/p.sum()

#http://stackoverflow.com/questions/13903922/multinomial-pmf-in-python-scipy-numpy
class Multinomial(object):
  def __init__(self, params):
    self._params = params

  def pmf(self, counts):
    if not(len(counts)==len(self._params)):
      raise ValueError("Dimensionality of count vector is incorrect")

    prob = 1.
    for i,c in enumerate(counts):
      prob *= self._params[i]**counts[i]

    return prob * exp(self._log_multinomial_coeff(counts))

  def log_pmf(self,counts):
    if not(len(counts)==len(self._params)):
      raise ValueError("Dimensionality of count vector is incorrect")

    prob = 0.
    for i,c in enumerate(counts):
      prob += counts[i]*log(self._params[i])

    return prob + self._log_multinomial_coeff(counts)

  def _log_multinomial_coeff(self, counts):
    return self._log_factorial(sum(counts)) - sum(self._log_factorial(c)
                                                    for c in counts)

  def _log_factorial(self, num):
    if not round(num)==num and num > 0:
      raise ValueError("Can only compute the factorial of positive ints")
    return sum(log(n) for n in range(1,num+1))

def MI_binary(b,W,pi,c,L,K):  #Mutual information(二値版):word_index、W、π、Ct
    #相互情報量の計算
    POC = W[c][b] * pi[c] #Multinomial(W[c]).pmf(B) * pi[c]   #場所の名前の多項分布と場所概念の多項分布の積
    PO = sum([W[ct][b] * pi[ct] for ct in xrange(L)]) #Multinomial(W[ct]).pmf(B)
    PC = pi[c]
    POb = 1.0 - PO
    PCb = 1.0 - PC
    PObCb = PCb - PO + POC
    POCb = PO - POC
    PObC = PC - POC
    #print POC,PO,PC,POb,PCb,PObCb,POCb,PObC
    
    # 相互情報量の定義の各項を計算
    temp1 = POC * log(POC/(PO*PC), 2)
    temp2 = POCb * log(POCb/(PO*PCb), 2)
    temp3 = PObC * log(PObC/(POb*PC), 2)
    temp4 = PObCb * log(PObCb/(POb*PCb), 2)
    score = temp1 + temp2 + temp3 + temp4
    return score

def Mutual_Info(W,pi):  #Mutual information:W、π 
    MI = 0
    for c in xrange(len(pi)):
      PC = pi[c]
      for j in xrange(len(W[c])):
        #B = [int(i==j) for i in xrange(len(W[c]))]
        PO = fsum([W[ct][j] * pi[ct] for ct in xrange(len(pi))])  #Multinomial(W[ct]).pmf(B)
        POC = W[c][j] * pi[c]   #場所の名前の多項分布と場所概念の多項分布の積
        
        
        # 相互情報量の定義の各項を計算
        MI = MI + POC * ( log((POC/(PO*PC)), 2) )
    
    return MI




###↓###ARI############################################ok
def ARI(cstep,CT,IT):  #Ct = []  推定された場所概念のindex  
  CtC = [0 for i in xrange(step)] #正解の分類結果
  ItC = [0 for i in xrange(step)] #正解の分類結果
  
  s = 1
  datasetNUM = 0
  datasetname = "" #datasets[int(datasetNUM)]
  #正解データを読み込みCT
  for line in open( datasetfolder + datasetname + correct_Ct, 'r'):
    itemList = line[:].split(',')
    for i in xrange(len(itemList)):
      if (itemList[i] != '') and (s <= step):
        CtC[i] = int(itemList[i])
      s += 1
  
  #ARIを計算
  print len(CtC),CtC
  print len(CT),CT
  ARI_CT = adjusted_rand_score(CtC, CT)
  print str(ARI_CT)
  
  s = 1
  #正解データを読み込みIT
  for line in open(datasetfolder + datasetname + correct_It, 'r'):
    itemList = line[:].split(',')
    for i in xrange(len(itemList)):
      if (itemList[i] != '') and (s <= step):
        ItC[i] = int(itemList[i])
      s += 1
  
  #ARIを計算
  print len(ItC),ItC
  print len(IT),IT  
  ARI_IT = adjusted_rand_score(ItC, IT)
  print str(ARI_IT)
  
  return ARI_CT, ARI_IT
###↑###ARI############################################

###↓###NMI############################################ok
def NMI(cstep,CT,IT):  #Ct = []  推定された場所概念のindex  
  CtC = [0 for i in xrange(step)] #正解の分類結果
  ItC = [0 for i in xrange(step)] #正解の分類結果
  
  s = 1
  datasetNUM = 0
  datasetname = "" #datasets[int(datasetNUM)]
  #正解データを読み込みCT
  for line in open( datasetfolder + datasetname + correct_Ct, 'r'):
    itemList = line[:].split(',')
    for i in xrange(len(itemList)):
      if (itemList[i] != '') and (s <= step):
        CtC[i] = int(itemList[i])
      s += 1
  
  #ARIを計算
  print len(CtC),CtC
  print len(CT),CT
  NMI_CT = normalized_mutual_info_score(CtC, CT)
  print str(NMI_CT)
  
  s = 1
  #正解データを読み込みIT
  for line in open(datasetfolder + datasetname + correct_It, 'r'):
    itemList = line[:].split(',')
    for i in xrange(len(itemList)):
      if (itemList[i] != '') and (s <= step):
        ItC[i] = int(itemList[i])
      s += 1
  
  #NMIを計算
  print len(ItC),ItC
  print len(IT),IT  
  NMI_IT = normalized_mutual_info_score(ItC, IT)
  print str(NMI_IT)
  
  return NMI_CT, NMI_IT
###↑###NMI############################################

def ReadTANGO(trialname):
  LIST = []
  TANGO = []
  
  ##単語辞書の読み込み
  for line in open(lmfolder + "phonemes.htkdic", 'r'):
      itemList = line[:-1].split('	')
      LIST = LIST + [line]
      for j in xrange(len(itemList)):
          itemList[j] = itemList[j].replace("[", "")
          itemList[j] = itemList[j].replace("]", "")
      
      TANGO = TANGO + [[itemList[1],itemList[2]]]
  
  ##単語辞書の読み込み
  for line in open(lmfolder + "web.000.htkdic", 'r'):
      itemList = line[:-1].split('	')
      LIST = LIST + [line]
      for j in xrange(len(itemList)):
          itemList[j] = itemList[j].replace("[", "")
          itemList[j] = itemList[j].replace("]", "")
      
      TANGO = TANGO + [[itemList[1],itemList[2]]]
  
  print "READ word dict."
  #print TANGO
  return TANGO

def ReadCorrectSentence(trialname, TANGO):
  #区切り位置も一文字としてカウントして計算。
  #音素は一文字ではないので、複数文字で表現された音素を別な記号に置き換える
  datasetNUM = 0
  datasetname = "" #datasets[int(datasetNUM)]
  RS = []      #認識音節列
  CS = []      #正解音節列
  RS_p = []      #認識音素列
  CS_p = []      #正解音素列
  
  TSEG = 0     #正解の単語分割数（分割文字+１）
  ESEG = 0     #推定の単語分割数（分割文字+１）
  
  j = 0
  for line in open(datasetfolder + datasetname + correct_data, 'r'):
        itemList = line[:-1].split(',')
        #itemList = itemList.replace(",", "")
        #W_index = W_index + [itemList]
        CS = CS + [[]]
        for i in xrange(len(itemList)):
          if itemList[i] != "":
            CS[j].append(itemList[i])
        j = j + 1
  print "READ correct data."
  
  #LIST = []
  hatsuon = [ "" for i in xrange(len(CS)) ]

  
  
  ##単語を順番に処理していく
  for c in xrange(len(CS)):   
    CS_p = CS_p + [[]]
    for jc in xrange(len(CS[c])):
          W_index_sj = unicode(CS[c][jc], encoding='shift_jis')
          hatsuon[c] = ""
          print W_index_sj
          #if len(W_index_sj) != 1:  ##１文字は除外
          #for moji in xrange(len(W_index_sj)):
          len_sj = len(W_index_sj)
          moji = 0
          while (moji < len_sj):
              flag_moji = 0
              #print len(W_index_sj), (W_index_sj),moji,(W_index_sj[moji]) #,str(W_index_sj),moji,W_index_sj[moji]#,len(unicode(W_index[i], encoding='shift_jis'))
              #print "moji:", moji, W_index_sj[moji]
              #print "hatsuon:",hatsuon
              if (W_index_sj[moji] == u' ') or (W_index_sj[moji] == ' '):
                hatsuon[c] = hatsuon[c] + str("|")
                moji = moji + 1
                flag_moji = 1
              for j in xrange(len(TANGO)):
                if (len(W_index_sj)-2 > moji) and (flag_moji == 0): 
                  #print TANGO[j],j
                  #print moji
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]+"_"+W_index_sj[moji+2]) and (W_index_sj[moji+1] == "_"): 
                    #print moji,j,TANGO[j][0]
                    hatsuon[c] = hatsuon[c] + TANGO[j][1]
                    moji = moji + 3
                    flag_moji = 1
                    
              for j in xrange(len(TANGO)):
                if (len(W_index_sj)-1 > moji) and (flag_moji == 0): 
                  #print TANGO[j],j
                  #print moji
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]+W_index_sj[moji+1]):
                    #print moji,j,TANGO[j][0]
                    hatsuon[c] = hatsuon[c] + TANGO[j][1]
                    moji = moji + 2
                    flag_moji = 1
                    
                #print len(W_index_sj),moji
              for j in xrange(len(TANGO)):
                if (len(W_index_sj) > moji) and (flag_moji == 0):
                  #else:
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]):
                      #print moji,j,TANGO[j][0]
                      hatsuon[c] = hatsuon[c] + TANGO[j][1]
                      moji = moji + 1
                      flag_moji = 1
          print "hatsuon",c,hatsuon[c]
          #CS_p = CS_p + [[]]
          CS_p[c] = CS_p[c] + [hatsuon[c]]
          #else:
          #  print W_index[c] + " (one name)"
        
  #一文字ではない表記の音素を別の文字へ置き換える	
  for c in xrange(len(CS_p)): 
    for j in xrange(len(CS_p[c])):
      CS_p[c][j] = CS_p[c][j].replace("my", "1")
      CS_p[c][j] = CS_p[c][j].replace("ky", "2")
      CS_p[c][j] = CS_p[c][j].replace("dy", "3")
      CS_p[c][j] = CS_p[c][j].replace("by", "4")
      CS_p[c][j] = CS_p[c][j].replace("gy", "5")
      CS_p[c][j] = CS_p[c][j].replace("ny", "6")
      CS_p[c][j] = CS_p[c][j].replace("hy", "7")
      CS_p[c][j] = CS_p[c][j].replace("ry", "8")
      CS_p[c][j] = CS_p[c][j].replace("py", "9")
      CS_p[c][j] = CS_p[c][j].replace("ts", "0")
      CS_p[c][j] = CS_p[c][j].replace("ch", "c")
      CS_p[c][j] = CS_p[c][j].replace("sh", "x")
      CS_p[c][j] = CS_p[c][j].replace(" ", "")
    #print "CS[%d]:%s" % (c,CS_p[c])
  print "Convert all correct words to phoneme form."
  N = 0
  return CS_p

###↓###文章まるごとのPAR############################################
def PAR_sentence(s, trialname, particle, CS_p, TANGO):
  #区切り位置も一文字としてカウントして計算。
  #音素は一文字ではないので、複数文字で表現された音素を別な記号に置き換える
  datasetNUM = 0
  datasetname = "" #datasets[int(datasetNUM)]
  RS = []      #認識音節列
  #CS = []      #正解音節列
  RS_p = []      #認識音素列
  #CS_p = []      #正解音素列
  
  TSEG = 0     #正解の単語分割数（分割文字+１）
  ESEG = 0     #推定の単語分割数（分割文字+１）

  N = 0
  
  # 最大尤度のパーティクルの単語分割結果を読み込み
  #if (os.path.exists(datafolder + trialname +  "/"+ str(s) + "/out_gmm/" + str(particle) + "_samp."+ str(samps) ) == True):
  if (1):
    #テキストファイルを読み込み
    for line in open(datafolder + trialname + "/" + str(s) + "/out_gmm/" + str(particle) + "_samp."+ str(samps) , 'r'):
        #######
        itemList = line[:-1]#.split(',')
        #itemList = itemList.replace(",", "")
        #<s>,<sp>,</s>を除く処理：単語に区切られていた場合
        #print itemList
        #<s>,<sp>,</s>を除く処理：単語中に存在している場合
        for j in xrange(len(itemList)):
          #itemList = itemList.replace("<s><s> ", "")
          itemList = itemList.replace("<sp>", "")
          itemList = itemList.replace("  ", " ")
          itemList = itemList.replace("  ", " ")
          itemList = itemList.replace("<s> ", "")
          #itemList = itemList.replace("<sp> ", "")
          #itemList = itemList.replace(" <sp>", "")
          itemList = itemList.replace("<s><s>", "")
          itemList = itemList.replace("<s>", "")
          itemList = itemList.replace(" </s>", "")
          itemList = itemList.replace("</s>", "")
          for b in xrange(5):
              itemList = itemList.replace("  ", " ")
        #W_index = W_index + [itemList]
        #for i in xrange(len(itemList)):
        if itemList != "":
          RS.append(itemList)
          #temp = temp + 1
          N = N + 1  #count
  
  hatsuon = [ "" for i in xrange(len(RS)) ]
  ##単語を順番に処理していく
  for c in xrange(len(RS)):   
          W_index_sj = unicode(RS[c], encoding='shift_jis')
          #if len(W_index_sj) != 1:  ##１文字は除外
          #for moji in xrange(len(W_index_sj)):
          moji = 0
          while (moji < len(W_index_sj)):
              flag_moji = 0
              #print len(W_index_sj),str(W_index_sj),moji,W_index_sj[moji]#,len(unicode(W_index[i], encoding='shift_jis'))
              if (W_index_sj[moji] == u' ') or (W_index_sj[moji] == ' '):
                hatsuon[c] = hatsuon[c] + str("|")
                moji = moji + 1
                flag_moji = 1
              for j in xrange(len(TANGO)):
                if (len(W_index_sj)-2 > moji) and (flag_moji == 0): 
                  #print TANGO[j],j
                  #print moji
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]+"_"+W_index_sj[moji+2]) and (W_index_sj[moji+1] == "_"): 
                    #print moji,j,TANGO[j][0]
                    hatsuon[c] = hatsuon[c] + TANGO[j][1]
                    moji = moji + 3
                    flag_moji = 1
                    
              for j in xrange(len(TANGO)):
                if (len(W_index_sj)-1 > moji) and (flag_moji == 0): 
                  #print TANGO[j],j
                  #print moji
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]+W_index_sj[moji+1]):
                    #print moji,j,TANGO[j][0]
                    hatsuon[c] = hatsuon[c] + TANGO[j][1]
                    moji = moji + 2
                    flag_moji = 1
                    
                #print len(W_index_sj),moji
              for j in xrange(len(TANGO)):
                if (len(W_index_sj) > moji) and (flag_moji == 0):
                  #else:
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]):
                      #print moji,j,TANGO[j][0]
                      hatsuon[c] = hatsuon[c] + TANGO[j][1]
                      moji = moji + 1
                      flag_moji = 1
          #print hatsuon[c]
          
          RS_p = RS_p + [hatsuon[c]]
          #else:
          #  print W_index[c] + " (one name)"
  
  #一文字ではない表記の音素を別の文字へ置き換える	
  for c in xrange(len(RS)): 
    RS_p[c] = RS_p[c].replace("my", "1")
    RS_p[c] = RS_p[c].replace("ky", "2")
    RS_p[c] = RS_p[c].replace("dy", "3")
    RS_p[c] = RS_p[c].replace("by", "4")
    RS_p[c] = RS_p[c].replace("gy", "5")
    RS_p[c] = RS_p[c].replace("ny", "6")
    RS_p[c] = RS_p[c].replace("hy", "7")
    RS_p[c] = RS_p[c].replace("ry", "8")
    RS_p[c] = RS_p[c].replace("py", "9")
    RS_p[c] = RS_p[c].replace("ts", "0")
    RS_p[c] = RS_p[c].replace("ch", "c")
    RS_p[c] = RS_p[c].replace("sh", "x")
    RS_p[c] = RS_p[c].replace(" ", "")
    #print RS_p[c]
    #print "RS[%d]:%s" % (c,RS_p[c])
  
  print "Convert all learned words to phoneme form."
  #print N
  #print CS
  #print RS
  
  LD = 0
  
  #print "LD:",LD
  #print "LD_sum:",LD_sum
  #print "CSN:",CSN
  #print "PER:"
  #print SER
  
  #一文一文のSERを出してそれを平均
  SER2 = 0.0
  TSEGtemp = 0
  ESEGtemp = 0
  
  for t in xrange(N):
    SER_temp = 1.0
    for j in xrange(len(CS_p[t])):
      ###編集距離
      LD = int( levenshtein_distance(unicode(RS_p[t], sys.stdin.encoding), unicode(CS_p[t][j], sys.stdin.encoding)) )
      print RS_p[t],CS_p[t][j],len(CS_p[t][j]),LD,float(LD)/(len(CS_p[t][j]))
      if ( (1.0 - SER_temp) <= (1.0 - (float(LD)/len(CS_p[t][j]))) ):
        SER_temp = float(LD)/(len(CS_p[t][j]))
        
      TSEGtemp = CS_p[t][j].count("|") + 1
      ESEGtemp = RS_p[t].count("|") + 1
      #print SER_temp
      
    SER2 = SER2 + SER_temp #float(LD)/(len(CS_p[t]))
    #print SER2
    
    TSEG += TSEGtemp
    ESEG += ESEGtemp
  
  SER2 = float(SER2) / N
  print "PAR_s:"
  #print SER2
  PAR_S = 1.0 - SER2
  print PAR_S
  
  return PAR_S,TSEG,ESEG
###↑###文章まるごとのPAR############################################


###↓###場所の名前のPAR############################################
def Name_of_Place(cstep, trialname, THETA, particle, L,K):
    datasetNUM = 0
    datasetname = "" #datasets[int(datasetNUM)]
    CN = []    #正解の音素列を格納する配列
    #correct_nameを読み込む
    for line in open(datasetfolder + datasetname + correct_name, 'r'):
        itemList = line[:-1].split(',')
        
        #W_index = W_index + [itemList]
        for i in xrange(len(itemList)):
          itemList[i] = itemList[i].replace(",", "")
          itemList[i] = itemList[i].replace("\r", "")
        if (itemList[0] != ""): # and (itemList[0] == itemList[1]):
            CN.append(itemList)
    
    
    #教示位置データを読み込み平均値を算出（xx,xy）
    XX = []
    count = 0
    
    ItC = []
    #それぞれの場所の中央座標を出す（10カ所）
    s = 0
    #正解データを読み込みIT
    for line in open(datasetfolder + datasetname + correct_It, 'r'):
      itemList = line[:].split(',')
      for i in xrange(len(itemList)):
        if (itemList[i] != '') and (s < step):
          ItC = ItC + [int(itemList[i])]
        s += 1
        
    ic = collections.Counter(ItC)
    icitems = ic.items()  # [(it番号,カウント数),(),...]
    
    #if (data_name != 'test000'):
    if (1):
        #Xt = []
        #最終時点step=50での位置座標を読み込み(これだと今のパーティクル番号の最終時刻の位置情報になるが細かいことは気にしない)
        Xt = np.array( ReadParticleData2(step,particle, trialname) )
        #ItC_cstep = [ItC[i] for i in xrange(cstep)]
        #ic_cstep = collections.Counter(ItC_cstep)
        #Ni = len(ic_cstep)  #cstepにおける教示した場所の種類数
        #icitems = ic_cstep.items()  # [(it番号,カウント数),(),...]
        #for i in xrange(cstep):
        #  Xt = [[p[r][0],p[r][1]]]
        
        #if i in xrange(len(ItC_step)):
        #  
        #  
        
        #for line3 in open(datafolder + trialname + '/'+ str(step) + '/particle'+ str(particle)+ ".csv" , 'r'):
        #  itemList3 = line3[:-1].split(' ')
        #  Xt = Xt + [(float(itemList3[0]), float(itemList3[1]))]
        #  count = count + 1
        
        #それぞれの場所の教示データの平均値を算出
        #for i in xrange(Ni):
        #  for j in xrange(len(ItC_cstep)):
        #    if (icitems[i][0] == j):
        #      
        
        for j in xrange(len(ic)):  #教示場所の種類数
          Xtemp  = []
          for i in xrange(len(ItC)): #要はステップ数（=50）
            if (icitems[j][0] == ItC[i]):
              Xtemp = Xtemp + [Xt[i]]
          
          print len(Xtemp),Xtemp,ic[icitems[j][0]]
          XX = XX + [sum(np.array(Xtemp))/float(ic[icitems[j][0]])]
          
          #for j in xrange(count[i]):
          #  
          #  #XX[i][0] = XX[i][0] + Xt[int(i*5 + j)][0]
          #  #XX[i][1] = XX[i][1] + Xt[int(i*5 + j)][1]
          #XX[i][0] = XX[i][0] / float(count[i])
          #XX[i][1] = XX[i][1] / float(count[i])
          #print XX
    
    print XX
    
    #THETA = [W,W_index,Myu,S,pi,phi_l]
    W = THETA[0]
    W_index = THETA[1]
    Myu = THETA[2]
    S = THETA[3]
    pi = THETA[4]
    phi_l = THETA[5]
    theta = THETA[6]
    
    
    POX_PAR = []
    
    ##教示位置データごとに
    for xdata in xrange(len(XX)):
    
      ###提案手法による尤度計算####################
      #Ot_index = 0
      pox = [0.0 for i in xrange(len(W_index))]
      for otb in xrange(len(W_index)):
        #Otb_B = [0 for j in xrange(len(W_index))]
        #Otb_B[Ot_index] = 1
        temp = [0.0 for c in range(L)]
        #print Otb_B
        for c in xrange(L) :
            ##場所の名前、多項分布の計算
            #W_temp = Multinomial(W[c])
            #temp[c] = W_temp.pmf(Otb_B)
            
            temp[c] = W[c][otb] * pi[c] 
            if (cstep == 1 or L == 1):
              temp[c] = temp[c]
            else:
              temp[c] = temp[c] #* MI_binary(otb,W,pi,c,L,K)
            ##場所概念の多項分布、piの計算
            #temp[c] = temp[c]
            
            ##itでサメーション
            it_sum = 0.0
            for it in xrange(K):
                if (S[it][0][0] < pow(10,-10)) or (S[it][1][1] < pow(10,-10)) :    ##共分散の値が0だとゼロワリになるので回避
                    if int(XX[xdata][0]) == int(Myu[it][0]) and int(XX[xdata][1]) == int(Myu[it][1]) :  ##他の方法の方が良いかも
                        g2 = 1.0
                        print "gauss 1"
                    else : 
                        g2 = 0.0
                        print "gauss 0"
                else : 
                    g2 = gaussian2d(XX[xdata][0],XX[xdata][1],Myu[it][0],Myu[it][1],S[it])  #2次元ガウス分布を計算
                it_sum = it_sum + g2 * phi_l[c][it]
                    
            temp[c] = temp[c] * it_sum
                    
        pox[otb] = sum(temp)
        
        #print Ot_index,pox[Ot_index]
        #Ot_index = Ot_index + 1
      #POX = POX + [pox.index(max(pox))]
      
      #print pox.index(max(pox))
      #print W_index_p[pox.index(max(pox))]
      
      
      #RS = [W_index[pox.index(max(pox))].replace(" ", "")]#[]      #認識音節列
      
      LIST = []
      hatsuon = "" #[ "" for i in xrange(len(W_index)) ]
      TANGO = []
      ##単語辞書の読み込み
      for line in open(lmfolder + "web.000.htkdic", 'r'):
        itemList = line[:-1].split('	')
        LIST = LIST + [line]
        for j in xrange(len(itemList)):
            itemList[j] = itemList[j].replace("[", "")
            itemList[j] = itemList[j].replace("]", "")
        
        TANGO = TANGO + [[itemList[1],itemList[2]]]
        
      
      #for c in xrange(len(W_index)):    # i_best = len(W_index)
      #W_index_sj = unicode(MI_best[c][i], encoding='shift_jis')
      W_index_sj = unicode(W_index[pox.index(max(pox))], encoding='shift_jis')
      #if len(W_index_sj) != 1:  ##１文字は除外
      #for moji in xrange(len(W_index_sj)):
      moji = 0
      while (moji < len(W_index_sj)):
              flag_moji = 0
              #print len(W_index_sj),str(W_index_sj),moji,W_index_sj[moji]#,len(unicode(W_index[i], encoding='shift_jis'))
              
              for j in xrange(len(TANGO)):
                if (len(W_index_sj)-2 > moji) and (flag_moji == 0): 
                  #print TANGO[j],j
                  #print moji
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]+"_"+W_index_sj[moji+2]) and (W_index_sj[moji+1] == "_"): 
                    #print moji,j,TANGO[j][0]
                    hatsuon = hatsuon + TANGO[j][1]
                    moji = moji + 3
                    flag_moji = 1
                    
              for j in xrange(len(TANGO)):
                if (len(W_index_sj)-1 > moji) and (flag_moji == 0): 
                  #print TANGO[j],j
                  #print moji
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]+W_index_sj[moji+1]):
                    #print moji,j,TANGO[j][0]
                    hatsuon = hatsuon + TANGO[j][1]
                    moji = moji + 2
                    flag_moji = 1
                    
                #print len(W_index_sj),moji
              for j in xrange(len(TANGO)):
                if (len(W_index_sj) > moji) and (flag_moji == 0):
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]):
                      #print moji,j,TANGO[j][0]
                      hatsuon = hatsuon + TANGO[j][1]
                      moji = moji + 1
                      flag_moji = 1
      #print hatsuon #[c]
      RS = [hatsuon]
      #else:
      #print W_index[c] + " (one name)"
      
      
      
      #RS = [W_index_p[pox.index(max(pox))].replace(" ", "")]#[]      #認識音節列
      PAR = 0.0
      for ndata in xrange(len(CN[xdata])):    
        CS = [CN[xdata][ndata]]  #[]      #正解音節列
        LD = 0
        #print CS,RS
        #print CS
        
        #一文字ではない表記の音素を別の文字へ置き換える	
        CS[0] = CS[0].replace("my", "1")
        CS[0] = CS[0].replace("ky", "2")
        CS[0] = CS[0].replace("dy", "3")
        CS[0] = CS[0].replace("by", "4")
        CS[0] = CS[0].replace("gy", "5")
        CS[0] = CS[0].replace("ny", "6")
        CS[0] = CS[0].replace("hy", "7")
        CS[0] = CS[0].replace("ry", "8")
        CS[0] = CS[0].replace("py", "9")
        CS[0] = CS[0].replace("ts", "0")
        CS[0] = CS[0].replace("ch", "c")
        CS[0] = CS[0].replace("sh", "x")
        CS[0] = CS[0].replace(" ", "")
        
        RS[0] = RS[0].replace("my", "1")
        RS[0] = RS[0].replace("ky", "2")
        RS[0] = RS[0].replace("dy", "3")
        RS[0] = RS[0].replace("by", "4")
        RS[0] = RS[0].replace("gy", "5")
        RS[0] = RS[0].replace("ny", "6")
        RS[0] = RS[0].replace("hy", "7")
        RS[0] = RS[0].replace("ry", "8")
        RS[0] = RS[0].replace("py", "9")
        RS[0] = RS[0].replace("ts", "0")
        RS[0] = RS[0].replace("ch", "c")
        RS[0] = RS[0].replace("sh", "x")
        RS[0] = RS[0].replace(" ", "")
        
        print CS,RS
        ###編集距離
        LD = int( levenshtein_distance(unicode(RS[0], sys.stdin.encoding), unicode(CS[0], sys.stdin.encoding)) )
        #print LD[t]
        
        
        CSN = len(CS[0])        #正解音節列の音節数
        #CSN = CSN/2    #文字コードの関係（2byte1文字のbyte換算のため）
        PER = float(LD)/CSN  #音節誤り率
        if (PAR <= (1.0 - PER)):        
            PAR = 1.0 - PER
      
        print "LD:",LD
        #print "LD_sum:",LD_sum
        print "CSN:",CSN
      print "PAR:"
      print PAR
      POX_PAR = POX_PAR + [PAR]
      
    #PARの平均値を算出
    PAR_mean = sum(POX_PAR) / len(XX)
    print PAR_mean
    
    
    return PAR_mean
###↑###場所の名前のPAR############################################

###↓###場所の名前のPAR############################################MI
def Name_of_Place_MI(cstep, trialname, THETA, particle, L,K, TANGO):
    datasetNUM = 0
    datasetname = "" #datasets[int(datasetNUM)]
    CN = []    #正解の音素列を格納する配列
    #correct_nameを読み込む
    for line in open(datasetfolder + datasetname + correct_name, 'r'):
        itemList = line[:-1].split(',')
        
        #W_index = W_index + [itemList]
        for i in xrange(len(itemList)):
          itemList[i] = itemList[i].replace(",", "")
          itemList[i] = itemList[i].replace("\r", "")
        if (itemList[0] != ""): # and (itemList[0] == itemList[1]):
            CN.append(itemList)
    
    
    #教示位置データを読み込み平均値を算出（xx,xy）
    XX = []
    count = 0
    
    ItC = []
    #それぞれの場所の中央座標を出す（10カ所）
    s = 0
    #正解データを読み込みIT
    for line in open(datasetfolder + datasetname + correct_It, 'r'):
      itemList = line[:].split(',')
      for i in xrange(len(itemList)):
        if (itemList[i] != '') and (s < step):
          ItC = ItC + [int(itemList[i])]
        s += 1
        
    ic = collections.Counter(ItC)
    icitems = ic.items()  # [(it番号,カウント数),(),...]
    
    #if (data_name != 'test000'):
    if (1):
        #Xt = []
        #最終時点step=50での位置座標を読み込み(これだと今のパーティクル番号の最終時刻の位置情報になるが細かいことは気にしない)
        Xt = np.array( ReadParticleData2(step,particle, trialname) )

        for j in xrange(len(ic)):  #教示場所の種類数
          Xtemp  = []
          for i in xrange(len(ItC)): #要はステップ数（=50）
            if (icitems[j][0] == ItC[i]):
              Xtemp = Xtemp + [Xt[i]]
          
          #print len(Xtemp),Xtemp,ic[icitems[j][0]]
          XX = XX + [sum(np.array(Xtemp))/float(ic[icitems[j][0]])]
          
    print XX
    
    #THETA = [W,W_index,Myu,S,pi,phi_l]
    W = THETA[0]
    W_index = THETA[1]
    Myu = THETA[2]
    S = THETA[3]
    pi = THETA[4]
    phi_l = THETA[5]
    theta = THETA[6]
    
    
    POX_PAR = []
    
    ##教示位置データごとに
    for xdata in xrange(len(XX)):
    
      ###提案手法による尤度計算####################
      #Ot_index = 0
      pox = [0.0 for i in xrange(len(W_index))]
      for otb in xrange(len(W_index)):
        #Otb_B = [0 for j in xrange(len(W_index))]
        #Otb_B[Ot_index] = 1
        temp = [0.0 for c in range(L)]
        #print Otb_B
        for c in xrange(L) :
            ##場所の名前、多項分布の計算
            #W_temp = Multinomial(W[c])
            #temp[c] = W_temp.pmf(Otb_B)
            
            temp[c] = W[c][otb] * pi[c] 
            if (cstep == 1 or L == 1):
              temp[c] = temp[c]
            else:
              temp[c] = temp[c] * MI_binary(otb,W,pi,c,L,K)
            ##場所概念の多項分布、piの計算
            #temp[c] = temp[c]
            
            ##itでサメーション
            it_sum = 0.0
            for it in xrange(K):
                if (S[it][0][0] < pow(10,-10)) or (S[it][1][1] < pow(10,-10)) :    ##共分散の値が0だとゼロワリになるので回避
                    if int(XX[xdata][0]) == int(Myu[it][0]) and int(XX[xdata][1]) == int(Myu[it][1]) :  ##他の方法の方が良いかも
                        g2 = 1.0
                        print "gauss 1"
                    else : 
                        g2 = 0.0
                        print "gauss 0"
                else : 
                    g2 = gaussian2d(XX[xdata][0],XX[xdata][1],Myu[it][0],Myu[it][1],S[it])  #2次元ガウス分布を計算
                it_sum = it_sum + g2 * phi_l[c][it]
                    
            temp[c] = temp[c] * it_sum
                    
        pox[otb] = sum(temp)
        
        #print Ot_index,pox[Ot_index]
        #Ot_index = Ot_index + 1
      #POX = POX + [pox.index(max(pox))]
      
      #print pox.index(max(pox))
      #print W_index_p[pox.index(max(pox))]
      
      
      #RS = [W_index[pox.index(max(pox))].replace(" ", "")]#[]      #認識音節列
      
      LIST = []
      hatsuon = "" #[ "" for i in xrange(len(W_index)) ]
      """
      TANGO = []
      ##単語辞書の読み込み
      for line in open(lmfolder + "web.000.htkdic", 'r'):
        itemList = line[:-1].split('	')
        LIST = LIST + [line]
        for j in xrange(len(itemList)):
            itemList[j] = itemList[j].replace("[", "")
            itemList[j] = itemList[j].replace("]", "")
        
        TANGO = TANGO + [[itemList[1],itemList[2]]]
      """
      
      #for c in xrange(len(W_index)):    # i_best = len(W_index)
      #W_index_sj = unicode(MI_best[c][i], encoding='shift_jis')
      W_index_sj = unicode(W_index[pox.index(max(pox))], encoding='shift_jis')
      #if len(W_index_sj) != 1:  ##１文字は除外
      #for moji in xrange(len(W_index_sj)):
      moji = 0
      while (moji < len(W_index_sj)):
              flag_moji = 0
              #print len(W_index_sj),str(W_index_sj),moji,W_index_sj[moji]#,len(unicode(W_index[i], encoding='shift_jis'))
              
              for j in xrange(len(TANGO)):
                if (len(W_index_sj)-2 > moji) and (flag_moji == 0): 
                  #print TANGO[j],j
                  #print moji
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]+"_"+W_index_sj[moji+2]) and (W_index_sj[moji+1] == "_"): 
                    #print moji,j,TANGO[j][0]
                    hatsuon = hatsuon + TANGO[j][1]
                    moji = moji + 3
                    flag_moji = 1
                    
              for j in xrange(len(TANGO)):
                if (len(W_index_sj)-1 > moji) and (flag_moji == 0): 
                  #print TANGO[j],j
                  #print moji
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]+W_index_sj[moji+1]):
                    #print moji,j,TANGO[j][0]
                    hatsuon = hatsuon + TANGO[j][1]
                    moji = moji + 2
                    flag_moji = 1
                    
                #print len(W_index_sj),moji
              for j in xrange(len(TANGO)):
                if (len(W_index_sj) > moji) and (flag_moji == 0):
                  if (unicode(TANGO[j][0], encoding='shift_jis') == W_index_sj[moji]):
                      #print moji,j,TANGO[j][0]
                      hatsuon = hatsuon + TANGO[j][1]
                      moji = moji + 1
                      flag_moji = 1
      #print hatsuon #[c]
      RS = [hatsuon]
      #else:
      #print W_index[c] + " (one name)"
      
      
      
      #RS = [W_index_p[pox.index(max(pox))].replace(" ", "")]#[]      #認識音節列
      PAR = 0.0
      for ndata in xrange(len(CN[xdata])):    
        CS = [CN[xdata][ndata]]  #[]      #正解音節列
        LD = 0
        #print CS,RS
        #print CS
        
        #一文字ではない表記の音素を別の文字へ置き換える	
        CS[0] = CS[0].replace("my", "1")
        CS[0] = CS[0].replace("ky", "2")
        CS[0] = CS[0].replace("dy", "3")
        CS[0] = CS[0].replace("by", "4")
        CS[0] = CS[0].replace("gy", "5")
        CS[0] = CS[0].replace("ny", "6")
        CS[0] = CS[0].replace("hy", "7")
        CS[0] = CS[0].replace("ry", "8")
        CS[0] = CS[0].replace("py", "9")
        CS[0] = CS[0].replace("ts", "0")
        CS[0] = CS[0].replace("ch", "c")
        CS[0] = CS[0].replace("sh", "x")
        CS[0] = CS[0].replace(" ", "")
        
        RS[0] = RS[0].replace("my", "1")
        RS[0] = RS[0].replace("ky", "2")
        RS[0] = RS[0].replace("dy", "3")
        RS[0] = RS[0].replace("by", "4")
        RS[0] = RS[0].replace("gy", "5")
        RS[0] = RS[0].replace("ny", "6")
        RS[0] = RS[0].replace("hy", "7")
        RS[0] = RS[0].replace("ry", "8")
        RS[0] = RS[0].replace("py", "9")
        RS[0] = RS[0].replace("ts", "0")
        RS[0] = RS[0].replace("ch", "c")
        RS[0] = RS[0].replace("sh", "x")
        RS[0] = RS[0].replace(" ", "")
        
        print CS,RS
        ###編集距離
        LD = int( levenshtein_distance(unicode(RS[0], sys.stdin.encoding), unicode(CS[0], sys.stdin.encoding)) )
        #print LD[t]
        
        
        CSN = len(CS[0])        #正解音節列の音節数
        #CSN = CSN/2    #文字コードの関係（2byte1文字のbyte換算のため）
        PER = float(LD)/CSN  #音節誤り率
        if (PAR <= (1.0 - PER)):        
            PAR = 1.0 - PER
      
        print "LD:",LD
        #print "LD_sum:",LD_sum
        print "CSN:",CSN
      print "PAR:"
      print PAR
      POX_PAR = POX_PAR + [PAR]
      
    #PARの平均値を算出
    PAR_mean = sum(POX_PAR) / len(XX)
    print PAR_mean
    
    
    return PAR_mean
###↑###場所の名前のPAR############################################MI


#itとCtのデータを読み込む（教示した時刻のみ）
def ReaditCtData(trialname, cstep, particle):
  CT,IT = [0 for i in xrange(step)],[0 for i in xrange(step)]
  i = 0
  if (step != 0):  #最初のステップ以外
    for line in open( datafolder + trialname + "/" + str(cstep) + "/particle" + str(particle) + ".csv" , 'r' ):
      itemList = line[:-1].split(',')
      CT[i] = int(itemList[7]) 
      IT[i] = int(itemList[8]) 
      i += 1
  return CT, IT

# Reading particle data (ID,x,y,theta,weight,previousID)
def ReadParticleData2(step, particle, trialname):
  p = []
  for line in open ( datafolder + trialname + "/"+ str(step) + "/particle" + str(particle) + ".csv" ):
    itemList = line[:-1].split(',')
    p.append( [float(itemList[2]), float(itemList[3])] )
    #p.append( Particle( int(itemList[0]), float(itemList[1]), float(itemList[2]), float(itemList[3]), float(itemList[4]), int(itemList[5])) )
  return p


#########################################################################
#パーティクル情報の読み込み For SIGVerse
def ReadParticleData2_SIGVerse(trialname, step):
  #CT,IT = [],[]
  CT = [ [0 for s in xrange(step-1)] for i in xrange(R) ]
  IT = [ [0 for s in xrange(step-1)] for i in xrange(R) ]
  #cstep = step - 1
  if (step != 1):
    #ID,x,y,theta,weight,pID,Ct,it
    r = 0
    for line in open( datafolder + trialname + "/" + str(step-1) + "/particles_NEW_CT.csv", 'r'):
        itemList = line[:-1].split(',')
        for i in range(len(itemList)):
          #CT.append( int(itemList[i]) )
          CT[r][i] = int(itemList[i])
        r += 1
    r = 0
    for line in open( datafolder + trialname + "/" + str(step-1) + "/particles_NEW_IT.csv", 'r'):
        itemList = line[:-1].split(',')
        for i in range(len(itemList)):
          #IT.append( int(itemList[i]) )
          IT[r][i] = int(itemList[i])
        r += 1
  #elif (step == 1):
  #  CT = [ [0 for s in xrange(step-1)] for i in xrange(R) ]
  #  IT = [ [0 for s in xrange(step-1)] for i in xrange(R) ]
  #  print "Initialize CT:",CT,"IT:",IT
  print "CT:",CT
  print "IT:",IT
  return CT,IT

  #for r in range(R):
  #  for s in xrange(step):
  #      #fp1.write( str(particles_NEW[r][0][s]) + ',' )
  #      #fp2.write( str(particles_NEW[r][1][s]) + ',' )
  #  #fp1.write('\n')
  #  #fp2.write('\n')    
#########################################################################

#########################################################################
#位置情報の読み込み For SIGVerse
def ReadPositionData_SIGVerse(trialname, datasetname, step):
  XT = []
  i = 0
  for line in open( datasetfolder + datasetname + data_name, 'r'):
      if (i < step):
        itemList = line[:].split(',')
        #XT.append( (float(itemList[0]), float(itemList[1])) )
        XT.append( Particle( int(i), float(itemList[0]), float(itemList[1]), float(0), float(1.0/R), int(0) ) )
      i += 1
  
  if( step != len(XT) ):
    print "ERROR XT", step, len(XT)
  #X_To = [ [Particle( int(0), float(1), float(2), float(3), float(4), int(5) ) for c in xrange(step)] for i in xrange(R) ]
  else:
    print "READ XT", step
  #print XT
  return XT
#########################################################################




def Evaluation(trialname):
  #MI_List = [[0.0 for i in xrange(R)] for j in xrange(step)]
  ARIc_List =  [[0.0 for i in xrange(R)] for j in xrange(step)]
  ARIi_List =  [[0.0 for i in xrange(R)] for j in xrange(step)]
  NMIc_List =  [[0.0 for i in xrange(R)] for j in xrange(step)]
  NMIi_List =  [[0.0 for i in xrange(R)] for j in xrange(step)]
  PARwMI_List = [[0.0 for i in xrange(R)] for j in xrange(step)]
  PARw_List = [[0.0 for i in xrange(R)] for j in xrange(step)]
  PARs_List = [[0.0 for i in xrange(R)] for j in xrange(step)]
  MAX_Samp =  [0 for j in xrange(step)]
  
  L = [[0.0 for i in xrange(R)] for j in xrange(step)]
  K = [[0.0 for i in xrange(R)] for j in xrange(step)]
  TSEG = [[0.0 for i in xrange(R)] for j in xrange(step)]
  ESEG = [[0.0 for i in xrange(R)] for j in xrange(step)]
  
  #イテレーションごとに選ばれた学習結果の評価値をすべて保存するファイル
  fp = open(datafolder + trialname + '/' + trialname + '_Evaluation2ALL.csv', 'w')  
  fp.write('ARIc,ARIi,NMIc,NMIi,PARwMI,PARw,L,K,TSEG,ESEG,PARs\n')
  
  #各stepの平均を保存
  fp2 = open(datafolder + trialname + '/' + trialname + '_meanEvaluation2ALL.csv', 'w')  
  fp2.write('ARIc,ARIi,NMIc,NMIi,PARwMI,PARw,L,K,TSEG,ESEG,PARs\n')
  
  #相互推定のイテレーションと単語分割結果の候補のすべてのパターンの評価値を保存
  #fp_ARIc =  open(datafolder + trialname + '/' + trialname + '_ARIc.csv', 'w')  
  #fp_ARIi =  open(datafolder + trialname + '/' + trialname + '_ARIi.csv', 'w')  
  #fp_PARs = open(datafolder + trialname + '/' + trialname + '_PARs.csv', 'w')  
  #fp_PARw = open(datafolder + trialname + '/' + trialname + '_PARw.csv', 'w')  
  #particle = open('./data/' + trialname + '/' + trialname + '_A_sougo_MI.csv', 'w')  
  
  TANGO = ReadTANGO(trialname)
  CS_p = ReadCorrectSentence(trialname, TANGO)

  #各stepごとの評価値を算出する
  for s in xrange(step):
    
    i = 0
    #重みファイルを読み込み
    for line in open(datafolder + trialname + '/'+ str(s+1) + '/weights.csv', 'r'):   ##読み込む
        #itemList = line[:-1].split(',')
        if (i == 0):
          MAX_Samp[s] = int(line)
        i += 1
    
    #最大尤度のパーティクル番号を保存
    particle = MAX_Samp[s]
    
    #各stepごとの全パーティクルの学習結果データを読み込む
    for r in xrange(R):
      #if (0):
      
      #各stepごとの最大尤度のパーティクル情報(CT,IT)を読み込む(for ARI)
      CT,IT = ReaditCtData(trialname, s+1, r)
      
      #推定されたLとKの数を読み込み
      i = 0
      for line in open(datafolder + trialname + '/'+ str(s+1) + '/index' + str(r) + '.csv', 'r'):   ##読み込む
        itemList = line[:-1].split(',')
        #itemint = [int(itemList[j]) for j in xrange(len(itemList))]
        print itemList
        if (i == 0):
          #for item in itemList:
          L[s][r] = len(itemList) -1
        elif (i == 1):
          K[s][r] = len(itemList) -1
        i += 1
      
      W_index= []
      
      i = 0
      #テキストファイルを読み込み
      for line in open(datafolder + trialname + '/'+ str(s+1) + '/W_list' + str(r) + '.csv', 'r'):   ##*_samp.100を順番に読み込む
        itemList = line[:-1].split(',')
        
        if(i == 0):
            for j in range(len(itemList)):
              if (itemList[j] != ""):
                W_index = W_index + [itemList[j]]
        i = i + 1
      
      #####パラメータW、μ、Σ、φ、πを入力する#####
      Myu = [ np.array([[ 0 ],[ 0 ]]) for i in xrange(K[s][r]) ]      #位置分布の平均(x,y)[K]
      S = [ np.array([ [0.0, 0.0],[0.0, 0.0] ]) for i in xrange(K[s][r]) ]      #位置分布の共分散(2×2次元)[K]
      W = [ [0.0 for j in xrange(len(W_index))] for c in xrange(L[s][r]) ]  #場所の名前(多項分布：W_index次元)[L]
      theta = [ [0.0 for j in xrange(DimImg)] for c in xrange(L[s][r]) ] 
      pi = [ 0 for c in xrange(L[s][r])]     #場所概念のindexの多項分布(L次元)
      phi_l = [ [0 for i in xrange(K[s][r])] for c in xrange(L[s][r]) ]  #位置分布のindexの多項分布(K次元)[L]
      
      #Ct = []
      
      i = 0
      ##Myuの読み込み
      for line in open(datafolder + trialname + '/'+ str(s+1) + '/mu' + str(r) + '.csv', 'r'):
        itemList = line[:-1].split(',')
        #itemList[1] = itemList[1].replace("_"+str(particle), "")
        Myu[i] = np.array([[ float(itemList[0]) ],[ float(itemList[1]) ]])
        
        i = i + 1
      
      i = 0
      ##Sの読み込み
      for line in open(datafolder + trialname + '/'+ str(s+1) + '/sig' + str(r) + '.csv', 'r'):
        itemList = line[:-1].split(',')
        #itemList[2] = itemList[2].replace("_"+str(particle), "")
        S[i] = np.array([[ float(itemList[0]), float(itemList[1]) ], [ float(itemList[2]), float(itemList[3]) ]])
        
        i = i + 1
      
      ##phiの読み込み
      c = 0
      #テキストファイルを読み込み
      for line in open(datafolder + trialname + '/'+ str(s+1) + '/phi' + str(r) + '.csv', 'r'):
        itemList = line[:-1].split(',')
        #print c
        #W_index = W_index + [itemList]
        for i in xrange(len(itemList)):
            if itemList[i] != "":
              phi_l[c][i] = float(itemList[i])
        c = c + 1
      
      
      ##piの読み込み
      for line in open(datafolder + trialname + '/'+ str(s+1) + '/pi' + str(r) + '.csv', 'r'):
        itemList = line[:-1].split(',')
        
        for i in xrange(len(itemList)):
          if itemList[i] != '':
            pi[i] = float(itemList[i])
      
      ##Wの読み込み
      c = 0
      #テキストファイルを読み込み
      for line in open(datafolder + trialname + '/'+ str(s+1) + '/W' + str(r) + '.csv', 'r'):
        itemList = line[:-1].split(',')
        #print c
        print len(W), len(W[c])
        #W_index = W_index + [itemList]
        for i in xrange(len(itemList)):
            if itemList[i] != '':
              #print "CHECK!!!!"
              #print datafolder, trialname, '/', str(s+1), '/W', str(r), '.csv'
              #print c,i,itemList[i]
              #print "CHECK!!!!!!"
              W[c][i] = float(itemList[i])
              
              #print itemList
        c = c + 1
      
      ##thetaの読み込み
      c = 0
      #テキストファイルを読み込み
      for line in open(datafolder + trialname + '/'+ str(s+1) + '/theta' + str(r) + '.csv', 'r'):
        itemList = line[:-1].split(',')
        #print c
        #W_index = W_index + [itemList]
        for i in xrange(len(itemList)):
            if itemList[i] != '':
              #print c,i,itemList[i]
              theta[c][i] = float(itemList[i])
              
              #print itemList
        c = c + 1
      
      
      #############################################################
      print s,r
      
      
      print "ARI"
      ARIc_List[s][r],ARIi_List[s][r] = ARI(s+1,CT,IT)
      
      print "NMI"
      NMIc_List[s][r],NMIi_List[s][r] = NMI(s+1,CT,IT)
      
      if(1):
        print "PAR_S"
        #TSEG = 0
        #ESEG = 0
        PARs_List[s][r],TSEG[s][r],ESEG[s][r] = PAR_sentence(s+1, trialname, r, CS_p, TANGO)
        
        THETA = [W,W_index,Myu,S,pi,phi_l,theta]
        #NOP = []
        ###print "PAR_W"
        ###PARw_List[s][r] = Name_of_Place(s+1, trialname, THETA, r, L[s][r], K[s][r])
        
        print "PAR_W_MI"
        PARwMI_List[s][r] = Name_of_Place_MI(s+1, trialname, THETA, r, L[s][r], K[s][r], TANGO)
    
    print "OK!"
    
    #最大尤度のパーティクルのみ保存
    fp.write( str(ARIc_List[s][particle])+','+ str(ARIi_List[s][particle])+','+ str(NMIc_List[s][particle])+','+ str(NMIi_List[s][particle])+','+ str(PARwMI_List[s][particle])+','+str(PARw_List[s][particle])+','+str(L[s][particle])+','+str(K[s][particle])+','+str(TSEG[s][particle])+','+str(ESEG[s][particle])+','+str(PARs_List[s][particle]) )
    fp.write('\n')
    
    #各ステップごとのパーティクル平均にする
    meanARIc = sum(ARIc_List[s])/float(R)
    meanARIi = sum(ARIi_List[s])/float(R)
    meanNMIc = sum(NMIc_List[s])/float(R)
    meanNMIi = sum(NMIi_List[s])/float(R)
    meanPARwMI = sum(PARwMI_List[s])/float(R)
    meanPARw = sum(PARw_List[s])/float(R)
    meanL = sum(L[s])/float(R)
    meanK = sum(K[s])/float(R)
    meanPARs = sum(PARs_List[s])/float(R)
    
    meanTSEG = sum(TSEG[s])/float(R)
    meanESEG = sum(ESEG[s])/float(R)
    
    fp2.write( str(meanARIc)+','+ str(meanARIi)+','+ str(meanNMIc)+','+ str(meanNMIi)+','+str(meanPARwMI)+','+str(meanPARw)+','+str(meanL)+','+str(meanK)+','+str(meanTSEG)+','+str(meanESEG)+','+str(meanPARs) )
    fp2.write('\n')
  
  print "close."
  
  fp.close()
  fp2.close()


if __name__ == '__main__':
    import sys
    #出力ファイル名を要求
    #trialname = raw_input("trialname?(folder) >") #"tamd2_sig_mswp_01" 
    trialname = sys.argv[1]
    print trialname
    
    Evaluation(trialname)
