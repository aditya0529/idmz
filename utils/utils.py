class Utility:
    # Class variable that stores the custom config passed from properties file
    cdk_custom_configs = {}

    @staticmethod
    def resource_name_helper(resource_name: str) -> str:
        """
        Helper method to append prefix and suffix to the resource name

        @param resource_name: Name of the resource

        @return: Modified name of the resource
        """
        return "sw-" + Utility.cdk_custom_configs["vpc_instance"] + "-" + \
            resource_name + "-" + \
            Utility.cdk_custom_configs["lzenv"] + "-aws"

    @staticmethod
    def load_properties(filepath, sep='=', comment_char='#'):
        """
        Read the file passed as parameter as a properties file.
        """
        props = {}
        with open(filepath, "rt") as f:
            for line in f:
                l = line.strip()
                if l and not l.startswith(comment_char):
                    key_value = l.split(sep)
                    key = key_value[0].strip()
                    value = sep.join(key_value[1:]).strip().strip('"')
                    props[key] = value
        return props
