import numpy as np
import tensorflow as tf

class Video_Caption_Generator():
    def __init__(self, dim_image, n_words, dim_hidden, batch_size, n_lstm_steps, n_video_lstm_step
                 ,n_caption_lstm_step,schedule_p, bias_init_vector=None):
        self.dim_image = dim_image
        self.n_words = n_words
        self.dim_hidden = dim_hidden
        self.batch_size = batch_size
        self.n_lstm_steps = n_lstm_steps
        self.n_video_lstm_step=n_video_lstm_step
        self.n_caption_lstm_step=n_caption_lstm_step
        self.schedule_p = schedule_p

        with tf.device("/cpu:0"):
            self.Wemb = tf.Variable(tf.random_uniform([n_words, dim_hidden], -0.1, 0.1), name='Wemb') # (token_unique, 1000)
        
        self.lstm1 = tf.nn.rnn_cell.BasicLSTMCell(dim_hidden, state_is_tuple=False) # c_state, m_state are concatenated along the column axis 
        self.lstm2 = tf.nn.rnn_cell.BasicLSTMCell(dim_hidden, state_is_tuple=False)

        self.encode_image_W = tf.Variable( tf.random_uniform([dim_image, dim_hidden], -0.1, 0.1), name='encode_image_W') # (4096, 1000)
        self.encode_image_b = tf.Variable( tf.zeros([dim_hidden]), name='encode_image_b')
        # variable for attention (hWz)
        self.attention_z = tf.Variable(tf.random_uniform([self.batch_size,self.lstm2.state_size],-0.1,0.1), name="attention_z")
        self.attention_W = tf.Variable(tf.random_uniform([self.lstm1.state_size,self.lstm2.state_size],-0.1,0.1),name="attention_W")
    
        self.embed_word_W = tf.Variable(tf.random_uniform([dim_hidden, n_words], -0.1,0.1), name='embed_word_W') # (1000, n_words)
        if bias_init_vector is not None:
            self.embed_word_b = tf.Variable(bias_init_vector.astype(np.float32), name='embed_word_b')
        else:
            self.embed_word_b = tf.Variable(tf.zeros([n_words]), name='embed_word_b')

    def build_model(self):
        video = tf.placeholder(tf.float32, [self.batch_size, self.n_video_lstm_step, self.dim_image]) # (batch, 80, 4096)
        video_mask = tf.placeholder(tf.float32, [self.batch_size, self.n_video_lstm_step])

        caption = tf.placeholder(tf.int32, [self.batch_size, self.n_caption_lstm_step+1]) # enclude <BOS>; store word ID; (batch, max_length)
        caption_mask = tf.placeholder(tf.float32, [self.batch_size, self.n_caption_lstm_step+1]) # (batch_size, max_length+1)
        video_flat = tf.reshape(video, [-1, self.dim_image]) 
        image_emb = tf.nn.xw_plus_b( video_flat, self.encode_image_W, self.encode_image_b ) # (batch_size*n_lstm_steps, dim_hidden)
        image_emb = tf.reshape(image_emb, [self.batch_size, self.n_lstm_steps, self.dim_hidden])
        print("lstm1 sate size,",self.lstm1.state_size)
        print("lstm2 sate size,",self.lstm2.state_size) # 2*hidden size 
        state1 = tf.zeros([self.batch_size, self.lstm1.state_size]) # initial state
        state2 = tf.zeros([self.batch_size, self.lstm2.state_size]) # initial state
        padding = tf.zeros([self.batch_size, self.dim_hidden]) # (batch, 1000)

        probs = []
        loss = 0.0
        
        ##############################  Encoding Stage ##################################
        context_padding = tf.zeros([self.batch_size, self.lstm2.state_size]) #(batch_size, 2000)
        h_list = []
        for i in range(0, self.n_video_lstm_step): # n_vedio_lstm_step = 80
            with tf.variable_scope("LSTM1", reuse= (i!=0)):
                output1, state1 = self.lstm1(image_emb[:,i,:], state1)
                h_list.append(state1)
            with tf.variable_scope("LSTM2", reuse=(i!=0)):
                output2, state2 = self.lstm2(tf.concat( [padding, output1, context_padding] ,1), state2)
        print(np.shape(h_list))
        h_list = tf.stack(h_list,axis=1) 
        print(np.shape(h_list)) # (64, 80, 2000)
        ############################# Decoding Stage ######################################
        for i in range(0, self.n_caption_lstm_step): ## Phase 2 => only generate captions
            if i==0:
                with tf.device("/cpu:0"):
                    current_embed = tf.nn.embedding_lookup(self.Wemb, caption[:, i])
            else: # schedule sampling
                print(self.schedule_p)
                if(np.random.binomial(1,self.schedule_p)==1): # schedule_p 擲骰子值出來是1的機率
                    with tf.device("/cpu:0"):
                        current_embed = tf.nn.embedding_lookup(self.Wemb, caption[:, i])
                else:
                    max_prob_index = tf.argmax(logit_words, 1)[0]
                    with tf.device("/cpu:0"):
                        current_embed = tf.nn.embedding_lookup(self.Wemb, max_prob_index)
            with tf.variable_scope("LSTM1",reuse= True):
                output1, state1 = self.lstm1(padding, state1)
            ##### attention ####
            context = []
            if i == 0:
                new_z = self.attention_z
            # h_list_flat = tf.reshape(h_list,[-1,self.lstm1.state_size])
            # print("h_list_flat shape, ", h_list_flat.shape) # 5120,2000
            
            h_list_flat = tf.reshape(h_list,[-1,self.lstm1.state_size])
            htmp = tf.matmul(h_list_flat,self.attention_W) # for matmul operation (5120,2000)
            hW = tf.reshape(htmp,[self.batch_size, self.n_video_lstm_step,self.lstm2.state_size])
            for x in range(0,self.batch_size):
                x_alpha = tf.reduce_sum(tf.multiply(hW[x,:,:],new_z[x,:]),axis=1)
                x_alpha = tf.nn.softmax(x_alpha)
                x_alpha = tf.expand_dims(x_alpha,1)
                x_new_z = tf.reduce_sum(tf.multiply(x_alpha,h_list[x,:,:]),axis=0)
                context.append(x_new_z) 
            context = tf.stack(context)
            print("context shape", context.shape)
            with tf.variable_scope("LSTM2", reuse= True):
                print(output1.shape) # (64,1000)
                output2, state2 = self.lstm2(tf.concat([current_embed, output1, context], 1), state2)
                new_z = state2
        
            labels = tf.expand_dims(caption[:, i+1], 1) # (batch, max_length, 1)
            indices = tf.expand_dims(tf.range(0, self.batch_size, 1), 1) # (batch_size, 1)
            concated = tf.concat([indices, labels], 1)
            onehot_labels = tf.sparse_to_dense(concated, tf.stack([self.batch_size, self.n_words]), 1.0, 0.0)

            logit_words = tf.nn.xw_plus_b(output2, self.embed_word_W, self.embed_word_b) #probability of each word
            cross_entropy = tf.nn.softmax_cross_entropy_with_logits(logits=logit_words, labels= onehot_labels)
            cross_entropy = cross_entropy * caption_mask[:,i]
            

            probs.append(logit_words)

            current_loss = tf.reduce_sum(cross_entropy)/self.batch_size
            loss = loss + current_loss
            
        return loss, video, video_mask, caption, caption_mask, probs
    
    def build_generator(self):

        # batch_size = 1
        context_padding = tf.zeros([1, self.lstm2.state_size])
        h_list = []
        video = tf.placeholder(tf.float32, [1, self.n_video_lstm_step, self.dim_image]) # (80, 4096)
        video_mask = tf.placeholder(tf.float32, [1, self.n_video_lstm_step])

        video_flat = tf.reshape(video, [-1, self.dim_image])
        image_emb = tf.nn.xw_plus_b(video_flat, self.encode_image_W, self.encode_image_b)
        image_emb = tf.reshape(image_emb, [1, self.n_video_lstm_step, self.dim_hidden])

        state1 = tf.zeros([1, self.lstm1.state_size])
        state2 = tf.zeros([1, self.lstm2.state_size])
        padding = tf.zeros([1, self.dim_hidden])

        generated_words = []

        probs = []
        embeds = []

        for i in range(0, self.n_video_lstm_step):
            with tf.variable_scope("LSTM1", reuse=(i!=0)):
                output1, state1 = self.lstm1(image_emb[:, i, :], state1)
                h_list.append(state1)

            with tf.variable_scope("LSTM2", reuse=(i!=0)):
                output2, state2 = self.lstm2(tf.concat([padding, output1, context_padding], 1), state2)
        h_list = tf.stack(h_list,axis=1) 
        for i in range(0, self.n_caption_lstm_step):
            if i == 0:
                with tf.device('/cpu:0'):
                    current_embed = tf.nn.embedding_lookup(self.Wemb, tf.ones([1], dtype=tf.int64))

            with tf.variable_scope("LSTM1", reuse=True):
                output1, state1 = self.lstm1(padding, state1)

            with tf.variable_scope("LSTM2", reuse=True):
                context = []
                if i == 0:
                    new_z = self.attention_z
                h_list_flat = tf.reshape(h_list,[-1,self.lstm1.state_size])
                htmp = tf.matmul(h_list_flat,self.attention_W)
                hW = tf.reshape(htmp, [1, self.n_video_lstm_step,self.lstm1.state_size])
                for x in range(0,1): # only one sample 
                    x_alpha = tf.reduce_sum(tf.multiply(hW[x,:,:],new_z[x,:]),axis=1)
                    x_alpha = tf.nn.softmax(x_alpha)
                    x_alpha = tf.expand_dims(x_alpha,1)
                    x_new_z = tf.reduce_sum(tf.multiply(x_alpha,h_list[x,:,:]),axis=0)
                    context.append(x_new_z)
                context = tf.stack(context)
                output2, state2 = self.lstm2(tf.concat([current_embed, output1,context],1), state2)
                new_z = state2
            logit_words = tf.nn.xw_plus_b( output2, self.embed_word_W, self.embed_word_b)
            max_prob_index = tf.argmax(logit_words, 1)[0]
            generated_words.append(max_prob_index)
            probs.append(logit_words)

            with tf.device("/cpu:0"):
                current_embed = tf.nn.embedding_lookup(self.Wemb, max_prob_index)
                current_embed = tf.expand_dims(current_embed, 0)

            embeds.append(current_embed)

        return video, video_mask, generated_words, probs, embeds