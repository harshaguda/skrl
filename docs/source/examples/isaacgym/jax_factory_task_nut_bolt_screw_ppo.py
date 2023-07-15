import isaacgym

import jax
import jax.numpy as jnp
import flax.linen as nn

# import the skrl components to build the RL system
from skrl.models.jax import Model, GaussianMixin, DeterministicMixin
from skrl.memories.jax import RandomMemory
from skrl.agents.jax.ppo import PPO, PPO_DEFAULT_CONFIG
from skrl.resources.preprocessors.jax import RunningStandardScaler
from skrl.trainers.jax import SequentialTrainer
from skrl.envs.jax import wrap_env
from skrl.envs.jax import load_isaacgym_env_preview4
from skrl.utils import set_seed
from skrl import config

config.jax.backend = "jax"  # or "numpy"


# seed for reproducibility
set_seed()


# define models (stochastic and deterministic models) using mixins
class Policy(GaussianMixin, Model):
    def __init__(self, observation_space, action_space, device=None, clip_actions=False,
                 clip_log_std=True, min_log_std=-20, max_log_std=2, reduction="sum", **kwargs):
        Model.__init__(self, observation_space, action_space, device, **kwargs)
        GaussianMixin.__init__(self, clip_actions, clip_log_std, min_log_std, max_log_std, reduction)

    @nn.compact  # marks the given module method allowing inlined submodules
    def __call__(self, inputs, role):
        x = nn.elu(nn.Dense(256)(inputs["states"]))
        x = nn.elu(nn.Dense(128)(x))
        x = nn.elu(nn.Dense(64)(x))
        x = nn.Dense(self.num_actions)(x)
        log_std = self.param("log_std", lambda _: jnp.zeros(self.num_actions))
        return x, log_std, {}

class Value(DeterministicMixin, Model):
    def __init__(self, observation_space, action_space, device=None, clip_actions=False, **kwargs):
        Model.__init__(self, observation_space, action_space, device, **kwargs)
        DeterministicMixin.__init__(self, clip_actions)

    @nn.compact  # marks the given module method allowing inlined submodules
    def __call__(self, inputs, role):
        x = nn.elu(nn.Dense(256)(inputs["states"]))
        x = nn.elu(nn.Dense(128)(x))
        x = nn.elu(nn.Dense(64)(x))
        x = nn.Dense(1)(x)
        return x, {}


# load and wrap the Isaac Gym environment
env = load_isaacgym_env_preview4(task_name="FactoryTaskNutBoltScrew")
env = wrap_env(env)

device = env.device


# instantiate a memory as rollout buffer (any memory can be used for this)
memory = RandomMemory(memory_size=128, num_envs=env.num_envs, device=device)


# instantiate the agent's models (function approximators).
# PPO requires 2 models, visit its documentation for more details
# https://skrl.readthedocs.io/en/latest/api/agents/ppo.html#models
models = {}
models["policy"] = Policy(env.observation_space, env.action_space, device)
models["value"] = Value(env.observation_space, env.action_space, device)

key = jax.random.PRNGKey(0)
models["policy"].init_state_dict(key, {"states": env.observation_space.sample()}, "policy")
models["value"].init_state_dict(key, {"states": env.observation_space.sample()}, "value")


# configure and instantiate the agent (visit its documentation to see all the options)
# https://skrl.readthedocs.io/en/latest/api/agents/ppo.html#configuration-and-hyperparameters
cfg = PPO_DEFAULT_CONFIG.copy()
cfg["rollouts"] = 128  # memory_size
cfg["learning_epochs"] = 8
cfg["mini_batches"] = 32  # 128 * 128 / 512
cfg["discount_factor"] = 0.99
cfg["lambda"] = 0.95
cfg["learning_rate"] = 1e-4
cfg["random_timesteps"] = 0
cfg["learning_starts"] = 0
cfg["grad_norm_clip"] = 0
cfg["ratio_clip"] = 0.2
cfg["value_clip"] = 0.2
cfg["clip_predicted_values"] = True
cfg["entropy_loss_scale"] = 0.0
cfg["value_loss_scale"] = 1.0
cfg["kl_threshold"] = 0.016
cfg["rewards_shaper"] = None
cfg["state_preprocessor"] = RunningStandardScaler
cfg["state_preprocessor_kwargs"] = {"size": env.observation_space, "device": device}
cfg["value_preprocessor"] = RunningStandardScaler
cfg["value_preprocessor_kwargs"] = {"size": 1, "device": device}
# logging to TensorBoard and write checkpoints (in timesteps)
cfg["experiment"]["write_interval"] = 614
cfg["experiment"]["checkpoint_interval"] = 6144
cfg["experiment"]["directory"] = "runs/jax/FactoryTaskNutBoltScrew"

agent = PPO(models=models,
            memory=memory,
            cfg=cfg,
            observation_space=env.observation_space,
            action_space=env.action_space,
            device=device)


# configure and instantiate the RL trainer
cfg_trainer = {"timesteps": 122880, "headless": True}
trainer = SequentialTrainer(cfg=cfg_trainer, env=env, agents=agent)

# start training
trainer.train()
