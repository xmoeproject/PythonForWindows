import dummy_wintypes
import itertools
from winstruct import WinStruct, WinUnion, WinStructType, Ptr, WinEnum
from simpleparser import *

class WinStructParser(Parser):
    def __init__(self, *args, **kwargs):
        super(WinStructParser, self).__init__(*args, **kwargs)
        self.pack = None

    def parse_array(self, ):
        self.assert_token_type(OpenSquareBracketToken)
        number = self.assert_token_type(NameToken).value
        self.assert_token_type(CloseSquareBracketToken)
        return number

    def parse_def(self):
        if self.peek() == KeywordToken("struct"):
            discard = self.next_token()

        def_type_tok  = self.assert_token_type(NameToken)
        def_type = WinStructType(def_type_tok.value)
        if type(self.peek()) == StarToken:
            def_type = Ptr(def_type)
            discard_star = self.next_token()

        def_name = self.assert_token_type(NameToken)

        if type(self.peek()) == ColonToken:
            self.next_token()
            return (def_type, def_name, 1)

        number_rep = self.parse_array()
        self.assert_token_type(ColonToken)
        return (def_type, def_name, number_rep)

    def parse_typedef(self, struct):
        if type(self.peek()) == ColonToken: # Just a ; no typedef
            self.next_token()
            return
        sep = CommaToken()
        while type(sep) == CommaToken:
            add_to_typedef = struct.add_typedef
            if type(self.peek()) == StarToken:
                self.next_token()
                add_to_typedef = struct.add_ptr_typedef
            name = self.assert_token_type(NameToken)
            # UGLY HACK for LDR definition
            if name.value == "RESTRICTED_POINTER":
                name = self.assert_token_type(NameToken)
            add_to_typedef(name.value)
            sep = self.next_token()
        self.assert_token_type(ColonToken, sep)

    def parse_enum(self):
        """Handle enum typedef with no value assignement and 1 typedef after"""
        enum_name = self.assert_token_type(NameToken).value
        res_enum = WinEnum(enum_name)
        self.assert_token_type(OpenBracketToken)
        count = itertools.count()
        assigned_value = False
        while type(self.peek()) != CloseBracketToken:
            i = next(count)
            name = self.assert_token_type(NameToken)
            if type(self.peek()) == EqualToken:
                if i != 0 and not assigned_value:
                    raise ParsingError("Enum {0} mix def with and without equal".format(enum_name))
                assigned_value = True
                self.assert_token_type(EqualToken)
                i = self.promote_to_int(self.next_token())
            else:
                if assigned_value:
                    raise ParsingError("Enum {0} mix def with and without equal".format(enum_name))

            res_enum.add_enum_entry(i, name.value)
            if not type(self.peek()) == CloseBracketToken:
                self.assert_token_type(CommaToken)

        self.assert_token_type(CloseBracketToken)
        self.parse_typedef(res_enum)
        #other_name = self.assert_token_type(NameToken).value
        #res_enum.add_typedef(other_name)
        #self.assert_token_type(ColonToken)
        return res_enum



    def parse_winstruct(self):
        is_typedef = False
        peeked = self.peek()
        if peeked == KeywordToken("typedef"):
            self.assert_keyword("typedef")
            is_typedef = True

        def_type = self.assert_token_type(KeywordToken)
        if def_type.value == "enum":
            return self.parse_enum()
        if def_type.value == "struct":
            WinDefType = WinStruct
        elif def_type.value == "union":
            WinDefType = WinUnion
        else:
            raise ParsingError("Expecting union or struct got <{0}> instead".format(def_type.value))
        struct_name = self.assert_token_type(NameToken)
        self.assert_token_type(OpenBracketToken)

        result = WinDefType(struct_name.value, self.pack)

        while type(self.peek()) != CloseBracketToken:
            tok_type, tok_name, nb_rep = self.parse_def()
            result.add_field((tok_type, tok_name.value, nb_rep))
        self.assert_token_type(CloseBracketToken)
        if is_typedef:
            self.parse_typedef(result)
        else:
            self.assert_token_type(ColonToken)
        return result

    def parse(self):
        strucs = []
        enums = []
        while self.peek() is not None:
            # HANDLE PRAGMA_PACK / PRAGMA_NOPACK
            if type(self.peek()) == NameToken:
                pragma = self.next_token().value
                if pragma == "PRAGMA_NOPACK":
                    self.pack = None
                    continue
                if pragma != "PRAGMA_PACK":
                    raise ValueError("Expected struct/union def or PRAGMA_[NO]PACK")
                pack_value = self.promote_to_int(self.next_token())
                self.pack = pack_value

            x = self.parse_winstruct()
            #x.packing = self.pack
            #if x.packing != None:
            #    print("{0} pack = {1}".format(x.name, x.packing))
            if type(x) == WinStruct or type(x) == WinUnion:
                strucs.append(x)
            elif type(x) == WinEnum:
                enums.append(x)
            else:
                raise ValueError("Unknow returned type {0}".format(x))
        return strucs, enums

class SimpleTypeDefine(object):
    def __init__(self, lvalue,  rvalue):
        self.lvalue = lvalue
        self.rvalue = rvalue

    def generate_ctypes(self):
        return "{self.lvalue} = {self.rvalue}".format(self=self)

class SimpleTypesParser(Parser):
    def __init__(self, data):
        self.lexer = iter(Lexer(self.initial_processing(data), newlinetoken=True))
        self.peek_token = None

    def parse(self):
        results = []
        while self.peek() is not None:
            lvalue = self.assert_token_type(NameToken).value
            self.assert_token_type(EqualToken)
            rvalue = ""
            while type(self.peek()) is not NewLineToken:
                rvalue += self.next_token().value
            results.append(SimpleTypeDefine(lvalue, rvalue))
            while type(self.peek()) is NewLineToken: # discard the NewLineToken(s)
                self.next_token()
        return results

def dbg_lexer(data):
    for i in Lexer(data).token_generation():
        print i

def dbg_parser(data):
    return WinStructParser(data).parse()

def dbg_validate(data):
    return validate_structs(Parser(data).parse())


if __name__ == "__main__":
    import sys
    #data = open(sys.argv[1], 'r').read()
    #ctypes_code = generate_ctypes(data)
