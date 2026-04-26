
#in ~/.ssh/config add 
#Host *
#  AddKeysToAgent yes
#
export SSH_AUTH_SOCK=/tmp/ssh-agent-$USER
if [[ ! -a $SSH_AUTH_SOCK ]] ; then
    ssh-agent -a $SSH_AUTH_SOCK
fi
