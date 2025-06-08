import configparser

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
        # This method relies on cdk_custom_configs being populated correctly
        # by the synthesizer with merged global and regional settings.
        return "sw-" + Utility.cdk_custom_configs.get("vpc_instance", "default_vpc_instance") + "-" + \
            resource_name + "-" + \
            Utility.cdk_custom_configs.get("lzenv", "default_lzenv") + "-aws"

    @staticmethod
    def load_properties(filepath): # Removed sep and comment_char as configparser handles them
        """
        Read the file passed as parameter as an INI-style properties file.
        Returns a dictionary of sections, where each section is a dictionary of its key-value pairs.
        """
        config = configparser.ConfigParser(inline_comment_prefixes=(';', '#')) # Enabled inline comment stripping
        # Preserve case for keys
        config.optionxform = str
        try:
            with open(filepath, "rt") as f:
                config.read_file(f)
        except FileNotFoundError:
            # Handle file not found gracefully, perhaps log an error or raise an exception
            print(f"Error: Properties file not found at {filepath}")
            return {} # Or raise an appropriate exception
        
        props = {section: dict(config.items(section)) for section in config.sections()}
        return props
