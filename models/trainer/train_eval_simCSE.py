# coding: UTF-8
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn import metrics
import time
from models.data_utils.simbert_data import get_time_dif
from transformers import AdamW
from transformers import get_linear_schedule_with_warmup

device = torch.device('cuda' if torch.cuda.is_available() else "cpu")

# simcse loss的理解可参考：https://zhuanlan.zhihu.com/p/377862950
def compute_sim_loss(outputs_cls):
    # outputs_cls [batch_size, 768]
    # y_true，以batch = 8 为例：[1,0,3,2,5，4,7,6]
    y_true = get_sim_label(outputs_cls).to(device)
    y_pred = F.normalize(outputs_cls, p=2, dim=1)
    similarities = torch.mm(y_pred, y_pred.t())
    similarities = similarities - (torch.eye(y_pred.shape[0]) * 1e12).to(device)  # 排除对角线
    similarities = similarities * 20  # scale

    index = [i for i in range(outputs_cls.shape[0])]
    np.random.shuffle(index)
    y_true = y_true[index]
    similarities = similarities[index]
    loss = F.cross_entropy(similarities, y_true)

    y_hat = torch.max(similarities, 1)[1]
    correct_sim = torch.sum(torch.eq(y_hat, y_true))

    return loss, correct_sim


def get_sim_label(outputs_cls):
    idxs = torch.arange(0, outputs_cls.shape[0])
    idxs_2 = (idxs + 1 - idxs % 2 * 2)
    return idxs_2


def train(args, model, train_loader):
    start_time = time.time()
    model.train()
    no_decay = ['bias', 'LayerNorm.bias', 'LayerNorm.weight']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)],
         'weight_decay': 0.01},
        {'params': [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
    ]

    optimizer = AdamW(optimizer_grouped_parameters, lr=args.learning_rate)
    # scheduler = get_linear_schedule_with_warmup(optimizer,
    #                                             num_warmup_steps= int(0.05 * len(train_loader) * config.num_epochs),
    #                                             num_training_steps=len(train_loader) * config.num_epochs)
    total_batch = 0  # 记录进行到多少batch
    best_loss = float('inf')
    model.train()
    loss_now = 0
    for epoch in range(args.num_epochs):
        print('Epoch [{}/{}]'.format(epoch + 1, args.num_epochs))
        for i, trains in enumerate(train_loader):
            improve = ''
            outputs_cls = model(trains)
            model.zero_grad()
            loss, correct_sim = compute_sim_loss(outputs_cls)
            loss.backward()
            optimizer.step()
            # scheduler.step()
            loss_now += loss
            if total_batch % args.save_steps == 0 and total_batch != 0:
                # 取前args.save_steps的均值作为模型保存指标
                if loss_now.item() / args.save_steps < best_loss:
                    best_loss = loss_now.item() / args.save_steps
                    model.bert.save_pretrained(args.save_path)
                    improve = '*'
                loss_now = 0
            if total_batch % args.report_steps == 0:
                # 每多少轮输出在训练集和验证集上的效果

                sim_acc = round(correct_sim.data.item() / len(trains[0]), 4)
                time_dif = get_time_dif(start_time)
                msg = 'Iter: {0:>6},  Sim Loss: {1:>5.4}, Sim Acc: {2:>6.2%}, Time: {3} {4}'
                print(msg.format(total_batch, loss.item(), sim_acc, time_dif, improve))
                model.train()
            total_batch += 1
