"""
solving pendulum using actor-critic model
"""

import tensorflow as tf
config = tf.ConfigProto(device_count={'GPU': 2})
config.gpu_options.allow_growth = True
SESS = tf.Session(config=config)

import gym
import numpy as np
from keras.models import Sequential, Model
from keras.layers.convolutional import Conv2D
from keras.layers import Input, Dense, Flatten, Reshape, BatchNormalization, Activation, regularizers, MaxPooling2D, UpSampling2D
from keras.layers.merge import Add, Multiply
from keras.optimizers import Adam
import keras.backend as K

import random
from collections import deque


# determines how to assign values to each state, i.e. takes the state
# and action (two-input model) and determines the corresponding value
class ActorCritic:
    def __init__(self, env, sess):
        self.env = env
        self.sess = sess

        self.learning_rate = 0.0001
        self.epsilon = 1.0
        self.epsilon_decay = .99998
        self.gamma = .95
        self.tau = .125

        # ===================================================================== #
        #                               Actor Model                             #
        # Chain rule: find the gradient of chaging the actor network params in  #
        # getting closest to the final value network predictions, i.e. de/dA    #
        # Calculate de/dA as = de/dC * dC/dA, where e is error, C critic, A act #
        # ===================================================================== #


        self.memory = deque(maxlen=2000)
        self.actor_state_input, self.actor_model = self.create_actor_model()
        _, self.target_actor_model = self.create_actor_model()

        self.actor_critic_grad = tf.placeholder(tf.float32,
                                                [None, self.env.action_space.shape[
                                                    0]])  # where we will feed de/dC (from critic)

        actor_model_weights = self.actor_model.trainable_weights
        self.actor_grads = tf.gradients(self.actor_model.output,
                                        actor_model_weights, -self.actor_critic_grad)  # dC/dA (from actor)
        grads = zip(self.actor_grads, actor_model_weights)
        self.optimize = tf.train.AdamOptimizer(self.learning_rate).apply_gradients(grads)

        # ===================================================================== #
        #                              Critic Model                             #
        # ===================================================================== #

        self.critic_state_input, self.critic_action_input, \
        self.critic_model = self.create_critic_model()
        _, _, self.target_critic_model = self.create_critic_model()

        self.critic_grads = tf.gradients(self.critic_model.output,
                                         self.critic_action_input)  # where we calcaulte de/dC for feeding above

        # Initialize for later gradient calculations
        self.sess.run(tf.initialize_all_variables())

    # ========================================================================= #
    #                              Model Definitions                            #
    # ========================================================================= #

    def create_actor_model(self):
        state_input = Input(shape=self.env.observation_space.shape)
        #h1 = Dense(24, activation='relu')(state_input)
        #h2 = Dense(48, activation='relu')(h1)
        #h3 = Dense(24, activation='relu')(h2)

        x = Conv2D(16, kernel_size=6, strides=(2, 1), padding='same', activation='linear')(state_input)
        x = BatchNormalization()(x)
        x = Activation('elu')(x)
        x = MaxPooling2D((2, 1), padding='same')(x)
        x = Conv2D(8, kernel_size=4, strides=(2, 2), padding='same', activation='linear')(x)
        x = Activation('elu')(x)
        x = Conv2D(8, kernel_size=4, strides=(2, 2), padding='same', activation='linear')(x)
        x = Activation('elu')(x)
        x = Flatten()(x)
        x = Dense(1024, activation='relu')(x)

        output = Dense(self.env.action_space.shape[0], activation='linear')(x)

        model = Model(input=state_input, output=output)
        adam = Adam(lr=0.001)
        print(model.summary())
        model.compile(loss="mse", optimizer=adam)
        return state_input, model

    def create_critic_model(self):
        state_input = Input(shape=self.env.observation_space.shape)
        x = Conv2D(16, kernel_size=6, strides=(2, 1), padding='same', activation='linear')(state_input)
        x = BatchNormalization()(x)
        x = Activation('elu')(x)
        x = MaxPooling2D((2, 1), padding='same')(x)
        x = Conv2D(8, kernel_size=4, strides=(2, 2), padding='same', activation='linear')(x)
        x = Activation('elu')(x)
        x = Conv2D(8, kernel_size=4, strides=(2, 2), padding='same', activation='linear')(x)
        x = Activation('elu')(x)
        x = Flatten()(x)
        x = Dense(1024, activation='relu')(x)

        action_input = Input(shape=self.env.action_space.shape)
        action_h1 = Dense(1024)(action_input)

        merged = Add()([x, action_h1])
        merged_h1 = Dense(128, activation='relu')(merged)
        output = Dense(1, activation='linear')(merged_h1)
        model = Model(input=[state_input, action_input], output=output)
        print(model.summary())
        adam = Adam(lr=0.001)
        model.compile(loss="mse", optimizer=adam)
        return state_input, action_input, model

    # ========================================================================= #
    #                               Model Training                              #
    # ========================================================================= #

    def remember(self, cur_state, action, reward, new_state, done):
        self.memory.append([cur_state, action, reward, new_state, done])

    def _train_actor(self, samples):
        for sample in samples:
            cur_state, action, reward, new_state, _ = sample
            predicted_action = self.actor_model.predict(np.stack([cur_state]))
            grads = self.sess.run(self.critic_grads, feed_dict={
                self.critic_state_input: np.stack([cur_state]),
                self.critic_action_input: predicted_action
            })[0]

            self.sess.run(self.optimize, feed_dict={
                self.actor_state_input: np.stack([cur_state]),
                self.actor_critic_grad: grads
            })

    def _train_critic(self, samples):
        for sample in samples:
            cur_state, action, reward, new_state, done = sample
            if not done:
                target_action = self.target_actor_model.predict(np.stack([new_state]))
                future_reward = self.target_critic_model.predict(
                    [np.stack([new_state]), target_action])[0][0]
                reward += self.gamma * future_reward
            self.critic_model.fit([np.stack([cur_state]), np.stack([action])], np.stack([reward]), verbose=0)

    def train(self):
        batch_size = 100
        if len(self.memory) < batch_size:
            return

        rewards = []
        samples = random.sample(self.memory, batch_size)
        self._train_critic(samples)
        self._train_actor(samples)

    # ========================================================================= #
    #                         Target Model Updating                             #
    # ========================================================================= #

    def _update_actor_target(self):
        actor_model_weights = self.actor_model.get_weights()
        actor_target_weights = self.target_critic_model.get_weights()

        for i in range(len(actor_target_weights)):
            actor_target_weights[i] = actor_model_weights[i]
        self.target_critic_model.set_weights(actor_target_weights)

    def _update_critic_target(self):
        critic_model_weights = self.critic_model.get_weights()
        critic_target_weights = self.critic_target_model.get_weights()

        for i in range(len(critic_target_weights)):
            critic_target_weights[i] = critic_model_weights[i]
        self.critic_target_model.set_weights(critic_target_weights)

    def update_target(self):
        self._update_actor_target()
        self._update_critic_target()

    # ========================================================================= #
    #                              Model Predictions                            #
    # ========================================================================= #

    def act(self, cur_state):
        self.epsilon *= self.epsilon_decay
        if np.random.random() < self.epsilon:
            return self.env.action_space.sample()
        return self.actor_model.predict(np.stack([cur_state]))[0]


def main():
    from tqdm import tqdm
    import matplotlib.pyplot as plt
    from gridworld.envs.GridworldFourRoomsContinuousEnv import GridworldFourRoomsContinuous
    K.set_session(SESS)
    env = GridworldFourRoomsContinuous()
    actor_critic = ActorCritic(env, SESS)

    num_trials = int(1e6)
    trial_len = 500

    cur_state = env.reset()
    action = env.action_space.sample()
    rewards = []
    episodes = 0
    pbar = tqdm(range(num_trials))
    for i in pbar:
        env.render()

        action = actor_critic.act(cur_state)
        new_state, reward, done, _ = env.step(action)

        actor_critic.remember(cur_state, action, reward, new_state, done)
        if i % 100 == 0:
            actor_critic.train()

        cur_state = new_state
        rewards.append(reward)
        if done:
            episodes +=1
        if len(rewards) > 10:
            pbar.set_description('r: {0:2.4f}\te: {1:1.4f}\td: {2:04d}'.format(np.mean(rewards[-10:]), actor_critic.epsilon, episodes))
        if episodes >= 100:
            env.render()


if __name__ == "__main__":
    main()
