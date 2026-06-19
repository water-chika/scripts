function add_path()
{
	case ":${PATH}:" in
		*:"$1":*)
			;;
		*)
			export PATH="$1:$PATH"
			;;
	esac
}
