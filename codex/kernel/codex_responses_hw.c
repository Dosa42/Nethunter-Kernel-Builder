#include <linux/fs.h>
#include <linux/init.h>
#include <linux/ioctl.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/uaccess.h>

#define CODEX_IOC_MAGIC 'C'
#define CODEX_IOC_FLASHLIGHT _IOW(CODEX_IOC_MAGIC, 0x01, int)

extern int codex_mt6360_set_torch(int state);

static long codex_responses_ioctl(struct file *file, unsigned int cmd,
                                  unsigned long arg)
{
    int state;

    if (cmd != CODEX_IOC_FLASHLIGHT)
        return -ENOTTY;
    if (copy_from_user(&state, (void __user *)arg, sizeof(state)))
        return -EFAULT;

    return codex_mt6360_set_torch(state ? 1 : 0);
}

static const struct file_operations codex_responses_fops = {
    .owner = THIS_MODULE,
    .unlocked_ioctl = codex_responses_ioctl,
#ifdef CONFIG_COMPAT
    .compat_ioctl = codex_responses_ioctl,
#endif
};

static struct miscdevice codex_responses_miscdev = {
    .minor = MISC_DYNAMIC_MINOR,
    .name = "codex_responses",
    .fops = &codex_responses_fops,
};

static int __init codex_responses_init(void)
{
    return misc_register(&codex_responses_miscdev);
}

static void __exit codex_responses_exit(void)
{
    misc_deregister(&codex_responses_miscdev);
}

module_init(codex_responses_init);
module_exit(codex_responses_exit);
MODULE_LICENSE("GPL");
