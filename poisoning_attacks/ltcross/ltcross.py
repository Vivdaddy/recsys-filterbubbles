import torch
import torch.nn as nn
import numpy as np
import pandas as  pd
import copy
import time
import argparse
import os
import rbo
from library_models import *
from library_data import *
from scipy import stats
from collections import defaultdict, Counter

def filter_and_split(data=[]):

    (users,counts) = np.unique(data[:,0],return_counts = True)
    
    users = users[counts>=10]

    sequence_dic,pert_dic =  {int(user):[] for user in set(data[:,0])}, {int(user):[] for user in set(data[:,0])}
    
    user_dic = {int(user):idx for (idx,user) in enumerate(users)}
    new_data = []
    for i in range(data.shape[0]):
        if int(data[i,0]) in user_dic:
            new_data.append([int(data[i,0]),int(data[i,1]),data[i,2],0])

    new_data = np.array(new_data)

    for i in range(new_data.shape[0]):
        sequence_dic[int(new_data[i,0])].append([i,int(new_data[i,1]),new_data[i,2]])
    
    test_len = 0
    for user in sequence_dic.keys():
        cur_test = int(0.1*len(sequence_dic[user]))
        for i in range(cur_test):
            interaction = sequence_dic[user].pop()
            new_data[interaction[0],3] = 1
        test_len += cur_test

    new_data = new_data[np.argsort(new_data[:,2]),:]
    print(data.shape,new_data.shape)
    return new_data,test_len

def main():
 
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_path',type=str,help='path of the dataset')
    parser.add_argument('--gpu',default='0',type=str,help='GPU# will be used')
    parser.add_argument('--attack_type',type=str, help = "Which attack will be tested")
    parser.add_argument('--attack_kind',type=str, help = "Deletion, Replacement, or Injection attack")
    parser.add_argument('--output',type=str, default = 'ltcross_output.txt', help = "Output file path")
    parser.add_argument('--epochs', default=50, type = int, help='number of training epochs')

    args = parser.parse_args()
    num_pert = 1
    os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"]=args.gpu
 
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(device)
    
    raw_data = pd.read_csv(args.data_path, sep='\t', header=None)
    data = raw_data.values[:,-3:]
    
    final_metrics = [[],[],[],[],[],[]]
    before_perf,after_perf = [[],[]],[[],[]]
    f = open(args.output,'w')

    (original_data,test_len) = filter_and_split(data=data)
    [user2id, user_sequence_id, user_timediffs_sequence, user_previous_itemid_sequence,
         item2id, item_sequence_id, item_timediffs_sequence, 
         timestamp_sequence, feature_sequence] = load_network(original_data)
    
    num_interactions = len(user_sequence_id)
    num_users = len(user2id) 
    num_items = len(item2id)+1 # one extra item for "none-of-these"
    num_features = len(feature_sequence[0])
    embedding_dim = 128
    
    occurence_count = Counter(original_data[:,1])
    popular_item = occurence_count.most_common(1)[0][0]
    least_popular_item = occurence_count.most_common()[-1][0]

    if args.attack_type == 'cas':
        in_degree, num_child = np.zeros(original_data.shape[0]),np.zeros(original_data.shape[0])
        user_dic,item_dic = defaultdict(list),defaultdict(list)
        edges = defaultdict(list)
        count = 0
        for i in range(original_data.shape[0]):
            in_degree[i]=-1
            if original_data[i,3]==0:
                count += 1
                user,item = int(original_data[i,0]),int(original_data[i,1])
                user_dic[user].append(i)
                item_dic[item].append(i)
                in_degree[i] = 0

        for user in user_dic.keys():
            cur_list = user_dic[user]
            for i in range(len(cur_list)-1):
                j,k = cur_list[i],cur_list[i+1]
                in_degree[k] += 1
                edges[j].append(k)

        for item in item_dic.keys():
            cur_list = item_dic[item]
            for i in range(len(cur_list)-1):
                j,k = cur_list[i],cur_list[i+1]
                in_degree[k] += 1
                edges[j].append(k)
        
        queue = []
        for i in range(original_data.shape[0]):
            if in_degree[i] == 0:
                queue.append(i)

        while len(queue)!=0:
            root = queue.pop(0)
            check = np.zeros(original_data.shape[0])
            check[root]=1
            q2 = [root]
            count2 = 1
            while len(q2)!=0:
                now = q2.pop(0)
                for node in edges[now]:
                    if check[node]==0:
                        check[node]=1
                        q2.append(node)
                        count2 += 1
            num_child[root] = count2

    for iteration in range(10): 
 
        model = ltcross(embedding_dim, num_features, num_users, num_items,0).to(device)
        print(num_users,num_items,num_features,num_interactions,model)
        original_model = copy.deepcopy(model)
        [original_probs,original_rank,temp,perf1] = model.traintest(data = original_data, perturbed_users = [], original_probs=-1, original_rank=-1, final_metrics = [],test_len = test_len,epochs = args.epochs,device=device) 
        perturbed_users = []

        if args.attack_type == 'cas':
 
            chosen = np.argsort(num_child)[-num_pert:] if num_pert!=0 else []

            if args.attack_kind=='deletion':
                tbd = []
                for idx in chosen:
                    maxv,maxp = num_child[idx],idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[CASSATA & Deletion] chosen interaction {}=({},{},{}) with cascading score {}'.format(maxp,user,item,time,maxv),file=f,flush=True)
                    tbd.append(maxp)
                    if user not in perturbed_users:
                        perturbed_users.append(user)
                new_data = np.delete(original_data,tbd,0)
            elif args.attack_kind=='injection':
                tbd,values = [],[]
                for idx in chosen:
                    maxv,maxp = num_child[idx],idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[CASSATA & Injection] chosen interaction {}=({},{},{}) with cascading {}'.format(maxp,user,item,time,maxv),file=f,flush=True)
                    replacement = int(least_popular_item)
#                    replacement = np.random.choice(list(set(original_data[:,1]))) 
                    tbd.append(maxp)
                    values.append([user,replacement,time-1,0])
                    if user not in perturbed_users:
                        perturbed_users.append(user)
                new_data = np.insert(original_data,tbd,values,axis=0)

            else:
                new_data = copy.deepcopy(original_data)
                for idx in chosen:
                    maxv,maxp = num_child[idx],idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[CASSATA & Replacement] chosen interaction {}=({},{},{}) with cascading score {}'.format(maxp,user,item,time,maxv),file=f,flush=True)
                    replacement = int(least_popular_item)
#                    replacement = np.random.choice(list(set(original_data[:,1])))
                    new_data[maxp,1] = replacement
                    if user not in perturbed_users:
                        perturbed_users.append(user)

        elif args.attack_type == 'opt':
            final_contribution = torch.zeros(original_data.shape[0])
            for i in range(original_data.shape[0]):
                if original_data[i, 3] == 0:
                    grad1 = model.inter[:, i, :].squeeze()
                    grad2 = model.inter2[:,i,:].squeeze()
                    sum1 = torch.sqrt(torch.sum(torch.mul(grad1,grad1))).item()
                    sum2 = torch.sqrt(torch.sum(torch.mul(grad2,grad2))).item()
                    final_contribution[i] = (sum1*sum2)

            chosen = np.argsort(final_contribution)[-num_pert:]
            if args.attack_kind=='deletion':
                tbd = []
                for idx in chosen:
                    maxv,maxp = final_contribution[idx],idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[Delete] Largest self-influence interaction {}=({},{},{}) with influence sum {}'.format(maxp,user,item,time,maxv),file=f,flush=True)
                    tbd.append(maxp)
                    if user not in perturbed_users:
                        perturbed_users.append(user)
                new_data = np.delete(original_data,tbd,0)
            elif args.attack_kind=='injection':
                tbd,values = [],[]
                for idx in chosen:
                    maxv,maxp = final_contribution[idx],idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[Inject] Largest self-influence interaction {}=({},{},{}) with influence sum {}'.format(maxp,user,item,time,maxv),file=f,flush=True)
                    replacement = np.random.choice(list(set(original_data[:,1]))) 
                    tbd.append(maxp)
                    values.append([user,replacement,time-1,0])
                    if user not in perturbed_users:
                        perturbed_users.append(user)
                new_data = np.insert(original_data,tbd,values,axis=0)
            else:
                new_data = copy.deepcopy(original_data)
                for idx in chosen:
                    maxv,maxp = final_contribution[idx],idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[Replace] Largest self-influence interaction {}=({},{},{}) with influence sum {}'.format(maxp,user,item,time,maxv),file=f,flush=True)
                    replacement = np.random.choice(list(set(original_data[:,1])))
                    new_data[maxp,1] = replacement
                    if user not in perturbed_users:
                        perturbed_users.append(user)

        elif args.attack_type=='random' or args.attack_type=='earliest':
            candidates,candidates2 = [],[]
            users = {}
            items = {}
            for i in range(original_data.shape[0]):
                if original_data[i,3]==0:
                    user,item = int(original_data[i,0]),int(original_data[i,1])
                    if user not in users:
                        candidates2.append(i)
                        users[user] = i
                    candidates.append(i)

            chosen = np.random.choice(candidates2,size = num_pert,replace=False) if args.attack_type == 'earliest' else np.random.choice(candidates,size = num_pert,replace=False)
            if args.attack_kind=='deletion':
                tbd = []
                for idx in chosen:
                    maxp=idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[Delete] chosen interaction {}=({},{},{})'.format(maxp,user,item,time),file=f,flush=True)
                    tbd.append(maxp)
                    if user not in perturbed_users:
                        perturbed_users.append(user)
                new_data = np.delete(original_data,tbd,0)
            elif args.attack_kind=='injection':
                tbd,values = [],[]
                for idx in chosen:
                    maxp=idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[Inject] chosen interaction {}=({},{},{})'.format(maxp,user,item,time),file=f,flush=True)
                    replacement = np.random.choice(list(set(original_data[:,1]))) 
                    tbd.append(maxp)
                    values.append([user,replacement,time-1,0])
                    if user not in perturbed_users:
                        perturbed_users.append(user)
                new_data = np.insert(original_data,tbd,values,axis=0)
            else:
                new_data = copy.deepcopy(original_data)
                for idx in chosen:
                    maxp=idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[Replace] chosen interaction {}=({},{},{})'.format(maxp,user,item,time),file=f,flush=True)
                    replacement = np.random.choice(list(set(original_data[:,1])))
                    new_data[maxp,1] = replacement
                    if user not in perturbed_users:
                        perturbed_users.append(user)
        else:  
            candidates = {}
            for i in range(original_data.shape[0]):
                if original_data[i,3]==0:
                    user = int(original_data[i,0])
                    candidates[user] = i

            chosen = np.random.choice(list(candidates.values()),size = num_pert,replace=False)
            if args.attack_kind=='deletion':
                tbd = []
                for idx in chosen:
                    maxp = idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[last&random deletion] perturbed interaction {}=({},{},{})'.format(maxp,user,item,time),file=f,flush=True)
                    tbd.append(maxp)
                    if user not in perturbed_users:
                        perturbed_users.append(user)
                new_data = np.delete(original_data,tbd,0)
            elif args.attack_kind=='injection':
                tbd,values = [],[]
                for idx in chosen:
                    maxp=idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[last&random injection] perturbed interaction {}=({},{},{})'.format(maxp,user,item,time),file=f,flush=True)
                    replacement = np.random.choice(list(set(original_data[:,1]))) 
                    tbd.append(maxp)
                    values.append([user,replacement,time-1,0])
                    if user not in perturbed_users:
                        perturbed_users.append(user)
                new_data = np.insert(original_data,tbd,values,axis=0) 
            else:
                new_data = copy.deepcopy(original_data)
                for idx in chosen:
                    maxp=idx
                    user,item,time = int(original_data[maxp,0]),int(original_data[maxp,1]),original_data[maxp,2]
                    print('[last&random replacement] perturbed interaction {}=({},{},{})'.format(maxp,user,item,time),file=f,flush=True)
                    new_data[maxp,1] = np.random.choice(list(set(original_data[:,1])))
                    if user not in perturbed_users:
                        perturbed_users.append(user)
        
        perturbed_users = [user2id[user] for user in perturbed_users]
        print(perturbed_users,new_data.shape)

        model = copy.deepcopy(original_model)
        [probs,rank,current_metrics,perf2] =  model.traintest(data=new_data, original_probs = original_probs, original_rank = original_rank, final_metrics = [[],[],[],[],[],[]],perturbed_users = perturbed_users,test_len = test_len,epochs = args.epochs,device=device)
        print('\nMRR_diff\tHITS_diff\tRBO\tRank_diff\tProb_diff\tTop-10 Jaccard',file=f,flush=True)
   
        for i in range(len(perf1)):
            before_perf[i].append(perf1[i])
            after_perf[i].append(perf2[i])

        for i in range(6):
            avg = np.average(current_metrics[i])
            med = np.median(current_metrics[i])
            std = np.std(current_metrics[i])
            final_metrics[i].append(avg)
            print('Avg = {}\tMed = {}\tStd = {}'.format(avg,med,std),file=f,flush=True)
        
        print('[Without perturbation] Avg MRR = {}\tAvg HITS@10 = {}'.format(np.average(before_perf[0]),np.average(before_perf[1])),file=f,flush=True)
        print('[With perturbation] Avg MRR = {}\tAvg HITS@10 = {}\n'.format(np.average(after_perf[0]),np.average(after_perf[1])),file=f,flush=True)

    for i in range(6):
        print(final_metrics[i],file=f,flush=True)

    for i in range(6):
        avg = np.average(final_metrics[i])
        print('({})'.format(avg),file=f,flush=True)
        
if __name__ == "__main__":
    main()
